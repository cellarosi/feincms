import re

import django
from django import forms, template
from django.conf import settings as django_settings
from django.contrib import admin
from django.contrib.admin import widgets
from django.contrib.admin.options import IncorrectLookupParameters
from django.contrib.admin.templatetags import admin_list
from django.contrib.admin.util import unquote
from django.core import serializers
from django.db import connection, transaction, models
from django.db.models import loading
from django.forms.formsets import all_valid
from django.forms.models import modelform_factory, inlineformset_factory
from django.http import HttpResponseRedirect, HttpResponse, Http404, \
    HttpResponseBadRequest
from django.shortcuts import render_to_response
from django.utils import dateformat, simplejson
from django.utils.html import escape, conditional_escape
from django.utils.encoding import force_unicode, smart_str, smart_unicode
from django.utils.functional import curry, update_wrapper
from django.utils.safestring import mark_safe
from django.utils.text import capfirst
from django.utils.translation import get_date_formats, get_partial_date_formats, ugettext as _

from feincms import settings
from feincms.models import Region
from feincms.module import django_boolean_icon

FRONTEND_EDITING_MATCHER = re.compile(r'(\d+)/(\w+)/(\d+)')


DJANGO10_COMPAT = django.VERSION[0] < 1 or (django.VERSION[0] == 1 and django.VERSION[1] < 1)


class ItemEditorForm(forms.ModelForm):
    region = forms.CharField(widget=forms.HiddenInput())
    ordering = forms.IntegerField(widget=forms.HiddenInput())


class ItemEditor(admin.ModelAdmin):
    """
    This ModelAdmin class needs an attribute:

    show_on_top::
        A list of fields which should be displayed at the top of the form.
        This does not need to (and should not) include ``template''
    """

    def _formfield_callback(self, request):
        if DJANGO10_COMPAT:
            # This should compare for Django SVN before [9761] (From 2009-01-16),
            # but I don't care that much. Doesn't work with git checkouts anyway, so...
            return self.formfield_for_dbfield
        else:
            return curry(self.formfield_for_dbfield, request=request)

    def _frontend_editing_view(self, request, cms_id, content_type, content_id):
        """
        This view is used strictly for frontend editing -- it is not used inside the
        standard administration interface.

        The code in feincms/templates/admin/feincms/fe_tools.html knows how to call
        this view correctly.
        """

        try:
            model_cls = loading.get_model(self.model._meta.app_label, content_type)
            obj = model_cls.objects.get(parent=cms_id, id=content_id)
        except:
            raise Http404

        form_class_base = getattr(model_cls, 'feincms_item_editor_form', ItemEditorForm)

        ModelForm = modelform_factory(model_cls,
            exclude=('parent', 'region', 'ordering'),
            form=form_class_base,
            formfield_callback=self._formfield_callback(request=request))

        # we do not want to edit these two fields in the frontend editing mode; we are
        # strictly editing single content blocks there.
        del ModelForm.base_fields['region']
        del ModelForm.base_fields['ordering']

        if request.method == 'POST':
            # The prefix is used to replace the formset identifier from the ItemEditor
            # interface. Customization of the form is easily possible through either matching
            # the prefix (frontend editing) or the formset identifier (ItemEditor) as it is
            # done in the richtext and mediafile init.html item editor includes.
            form = ModelForm(request.POST, instance=obj, prefix=content_type)

            if form.is_valid():
                obj = form.save()

                return render_to_response('admin/feincms/fe_editor_done.html', {
                    'content': obj.render(request=request),
                    'identifier': obj.fe_identifier(),
                    'FEINCMS_ADMIN_MEDIA': settings.FEINCMS_ADMIN_MEDIA,
                    'FEINCMS_ADMIN_MEDIA_HOTLINKING': settings.FEINCMS_ADMIN_MEDIA_HOTLINKING,
                    })
        else:
            form = ModelForm(instance=obj, prefix=content_type)

        return render_to_response('admin/feincms/fe_editor.html', {
            'frontend_editing': True,
            'title': _('Change %s') % force_unicode(model_cls._meta.verbose_name),
            'object': obj,
            'form': form,
            'is_popup': True,
            'media': self.media,
            'FEINCMS_ADMIN_MEDIA': settings.FEINCMS_ADMIN_MEDIA,
            'FEINCMS_ADMIN_MEDIA_HOTLINKING': settings.FEINCMS_ADMIN_MEDIA_HOTLINKING,
            }, context_instance=template.RequestContext(request,
                processors=self.model.feincms_item_editor_context_processors))

    def change_view(self, request, object_id, extra_context=None):
        self.model._needs_content_types()

        # Recognize frontend editing requests
        # This is done here so that the developer does not need to add additional entries to
        # urls.py or something...
        res = FRONTEND_EDITING_MATCHER.search(object_id)

        if res:
            return self._frontend_editing_view(request, res.group(1), res.group(2), res.group(3))

        ModelForm = modelform_factory(self.model, exclude=('parent',),
            formfield_callback=self._formfield_callback(request=request))
        SettingsForm = modelform_factory(self.model,
            exclude=self.show_on_top + ('template_key', 'parent'),
            formfield_callback=self._formfield_callback(request=request))

        # generate a formset type for every concrete content type
        inline_formset_types = [(
            content_type,
            inlineformset_factory(self.model, content_type, extra=1,
                form=getattr(content_type, 'feincms_item_editor_form', ItemEditorForm),
                formfield_callback=self._formfield_callback(request=request))
            ) for content_type in self.model._feincms_content_types]

        opts = self.model._meta
        app_label = opts.app_label
        obj = self.model._default_manager.get(pk=unquote(object_id))

        if not self.has_change_permission(request, obj):
            raise PermissionDenied

        if request.method == 'POST':
            model_form = ModelForm(request.POST, request.FILES, instance=obj)

            inline_formsets = [
                formset_class(request.POST, request.FILES, instance=obj,
                    prefix=content_type.__name__.lower())
                for content_type, formset_class in inline_formset_types]

            if model_form.is_valid() and all_valid(inline_formsets):
                model_form.save()
                for formset in inline_formsets:
                    formset.save()

                msg = _('The %(name)s "%(obj)s" was changed successfully.') % {'name': force_unicode(opts.verbose_name), 'obj': force_unicode(obj)}
                if request.POST.has_key("_continue"):
                    self.message_user(request, msg + ' ' + _("You may edit it again below."))
                    return HttpResponseRedirect('.')
                elif request.POST.has_key('_addanother'):
                    self.message_user(request, msg + ' ' + (_("You may add another %s below.") % force_unicode(opts.verbose_name)))
                    return HttpResponseRedirect("../add/")
                else:
                    self.message_user(request, msg)
                    return HttpResponseRedirect("../")

            settings_fieldset = SettingsForm(request.POST, instance=obj)
            settings_fieldset.is_valid()
        else:
            model_form = ModelForm(instance=obj)
            inline_formsets = [
                formset_class(instance=obj, prefix=content_type.__name__.lower())
                for content_type, formset_class in inline_formset_types]

            settings_fieldset = SettingsForm(instance=obj)

        content_types = []
        for content_type in self.model._feincms_content_types:
            content_name = content_type._meta.verbose_name
            content_types.append((content_name, content_type.__name__.lower()))

        context = {
            'title': _('Change %s') % force_unicode(opts.verbose_name),
            'opts': opts,
            'object': obj,
            'object_form': model_form,
            'inline_formsets': inline_formsets,
            'content_types': content_types,
            'settings_fieldset': settings_fieldset,
            'top_fieldset': [model_form[field] for field in self.show_on_top],
            'media': self.media + model_form.media,
            'FEINCMS_ADMIN_MEDIA': settings.FEINCMS_ADMIN_MEDIA,
            'FEINCMS_ADMIN_MEDIA_HOTLINKING': settings.FEINCMS_ADMIN_MEDIA_HOTLINKING,
        }

        return render_to_response([
            'admin/feincms/%s/%s/item_editor.html' % (app_label, opts.object_name.lower()),
            'admin/feincms/%s/item_editor.html' % app_label,
            'admin/feincms/item_editor.html',
            ], context, context_instance=template.RequestContext(request,
                processors=self.model.feincms_item_editor_context_processors))


class TreeEditor(admin.ModelAdmin):
    actions = None # TreeEditor does not like the checkbox column

    def changelist_view(self, request, extra_context=None):
        # handle AJAX requests
        if request.is_ajax():
            cmd = request.POST.get('__cmd')
            if cmd == 'save_tree':
                return self._save_tree(request)
            elif cmd == 'delete_item':
                return self._delete_item(request)
            elif cmd == 'toggle_boolean':
                return self._toggle_boolean(request)

            return HttpResponse('Oops. AJAX request not understood.')

        from django.contrib.admin.views.main import ChangeList, ERROR_FLAG
        opts = self.model._meta
        app_label = opts.app_label

        if not self.has_change_permission(request, None):
            raise PermissionDenied
        try:
            if DJANGO10_COMPAT:
                self.changelist = ChangeList(request, self.model, self.list_display,
                    self.list_display_links, self.list_filter, self.date_hierarchy,
                    self.search_fields, self.list_select_related, self.list_per_page,
                    self)
            else:
                self.changelist = ChangeList(request, self.model, self.list_display,
                    self.list_display_links, self.list_filter, self.date_hierarchy,
                    self.search_fields, self.list_select_related, self.list_per_page,
                    self.list_editable, self)
        except IncorrectLookupParameters:
            # Wacky lookup parameters were given, so redirect to the main
            # changelist page, without parameters, and pass an 'invalid=1'
            # parameter via the query string. If wacky parameters were given and
            # the 'invalid=1' parameter was already in the query string, something
            # is screwed up with the database, so display an error page.
            if ERROR_FLAG in request.GET.keys():
                return render_to_response('admin/invalid_setup.html', {'title': _('Database error')})
            return HttpResponseRedirect(request.path + '?' + ERROR_FLAG + '=1')

        # XXX Hack alarm!
        # if actions is defined, Django adds a new field to list_display, action_checkbox. The
        # TreeEditor cannot cope with this (yet), so we remove it by hand.
        if 'action_checkbox' in self.changelist.list_display:
            self.changelist.list_display.remove('action_checkbox')

        context = {
            'FEINCMS_ADMIN_MEDIA': settings.FEINCMS_ADMIN_MEDIA,
            'FEINCMS_ADMIN_MEDIA_HOTLINKING': settings.FEINCMS_ADMIN_MEDIA_HOTLINKING,
            'title': self.changelist.title,
            'is_popup': self.changelist.is_popup,
            'cl': self.changelist,
            'has_add_permission': self.has_add_permission(request),
            'root_path': self.admin_site.root_path,
            'app_label': app_label,
            'object_list': self.model._tree_manager.all(),
            'tree_editor': self,

            'result_headers': list(admin_list.result_headers(self.changelist)),
        }
        context.update(extra_context or {})
        return render_to_response([
            'admin/feincms/%s/%s/tree_editor.html' % (app_label, opts.object_name.lower()),
            'admin/feincms/%s/tree_editor.html' % app_label,
            'admin/feincms/tree_editor.html',
            ], context, context_instance=template.RequestContext(request))

    def object_list(self):
        first_field = self.changelist.list_display[0]

        ancestors = []

        for item in self.model._tree_manager.all().select_related():
            first = getattr(item, first_field)
            if callable(first):
                first = first()

            if item.parent_id is None:
                ancestors.append(0)
            else:
                ancestors.append(item.parent_id)

            if item.parent_id is not None:
                item.parent_node_index = ancestors.index(item.parent_id)
            else:
                item.parent_node_index = 'none'

            yield item, first, _properties(self.changelist, item)

    def _save_tree(self, request):
        itemtree = simplejson.loads(request.POST['tree'])

        TREE_ID = 0; PARENT_ID = 1; LEFT = 2; RIGHT = 3; LEVEL = 4; ITEM_ID = 5

        tree_id = 0
        parents = []
        node_indices = {}

        data = []

        def indexer(start):
            while True:
                yield start
                start += 1

        left = indexer(0)

        for item_id, parent_id, is_parent in itemtree:
            node_indices[item_id] = len(node_indices)

            if parent_id in parents:
                for i in range(len(parents) - parents.index(parent_id) - 1):
                    data[node_indices[parents.pop()]][RIGHT] = left.next()
            elif not parent_id:
                while parents:
                    data[node_indices[parents.pop()]][RIGHT] = left.next()
                left = indexer(0)
                tree_id += 1

            data.append([
                tree_id,
                parent_id and parent_id or None,
                left.next(),
                0,
                len(parents),
                item_id,
                ])

            if is_parent:
                parents.append(item_id)
            else:
                data[-1][RIGHT] = left.next()

        while parents:
            data[node_indices[parents.pop()]][RIGHT] = left.next()

        # 0 = tree_id, 1 = parent_id, 2 = left, 3 = right, 4 = level, 5 = item_id
        sql = "UPDATE %s SET %s=%%s, %s_id=%%s, %s=%%s, %s=%%s, %s=%%s WHERE %s=%%s" % (
            self.model._meta.db_table,
            self.model._meta.tree_id_attr,
            self.model._meta.parent_attr,
            self.model._meta.left_attr,
            self.model._meta.right_attr,
            self.model._meta.level_attr,
            self.model._meta.pk.column)

        connection.cursor().executemany(sql, data)

        # call save on all toplevel objects, thereby ensuring that caches are regenerated (if they
        # exist)
        # XXX This is currently only really needed for the page module, I should probably use a
        # signal for this
        for item in self.model._tree_manager.root_nodes():
            item.save()

        return HttpResponse("OK", mimetype="text/plain")

    def _delete_item(self, request):
        item_id = request.POST['item_id']
        try:
            obj = self.model._default_manager.get(pk=unquote(item_id))
            obj.delete()
        except Exception, e:
            return HttpResponse("FAILED " + str(e), mimetype="text/plain")

        return HttpResponse("OK", mimetype="text/plain")

    def _toggle_boolean(self, request):
        if not hasattr(self, '_ajax_editable_booleans'):
            self._ajax_editable_booleans = []

            for field in self.list_display:
                item = getattr(self.__class__, field, None)
                if not item:
                    continue

                attr = getattr(item, 'editable_boolean_field', None)
                if attr:
                    self._ajax_editable_booleans.append(attr)

        item_id = request.POST['item_id']
        attr = request.POST['attr']

        if attr not in self._ajax_editable_booleans:
            return HttpResponseBadRequest()

        try:
            obj = self.model._default_manager.get(pk=unquote(item_id))
            setattr(obj, attr, not getattr(obj, attr))
            obj.save()
        except Exception, e:
            return HttpResponse("FAILED " + str(e), mimetype="text/plain")

        data = [(obj.id, ajax_editable_boolean_cell(obj, attr))]

        # TODO descend recursively, sometimes (f.e. for Page.active)

        return HttpResponse(simplejson.dumps(data), mimetype="application/json")


def ajax_editable_boolean_cell(item, attr):
    return '<a class="attr_%s" href="#" onclick="return toggle_boolean(this, \'%s\')">%s</a>' % (
        attr, attr, django_boolean_icon(getattr(item, attr), 'toggle %s' % attr))


def ajax_editable_boolean(attr, short_description):
    def _fn(self, item):
        return ajax_editable_boolean_cell(item, attr)
    _fn.allow_tags = True
    _fn.short_description = short_description
    _fn.editable_boolean_field = attr
    return _fn


def _properties(cl, result):
    first = True
    pk = cl.lookup_opts.pk.attname
    EMPTY_CHANGELIST_VALUE = '(None)'

    for field_name in cl.list_display[1:]:
        try:
            f = cl.lookup_opts.get_field(field_name)
        except models.FieldDoesNotExist:
            try:
                if callable(field_name):
                    attr = field_name
                    value = attr(result)
                elif hasattr(cl.model_admin, field_name) and \
                   not field_name == '__str__' and not field_name == '__unicode__':
                    attr = getattr(cl.model_admin, field_name)
                    value = attr(result)
                else:
                    attr = getattr(result, field_name)
                    if callable(attr):
                        value = attr()
                    else:
                        value = attr
                allow_tags = getattr(attr, 'allow_tags', False)
                boolean = getattr(attr, 'boolean', False)
                if boolean:
                    allow_tags = True
                    result_repr = django_boolean_icon(value)
                else:
                    result_repr = smart_unicode(value)
            except (AttributeError, models.ObjectDoesNotExist):
                result_repr = EMPTY_CHANGELIST_VALUE
            else:
                # Strip HTML tags in the resulting text, except if the
                # function has an "allow_tags" attribute set to True.
                if not allow_tags:
                    result_repr = escape(result_repr)
                else:
                    result_repr = mark_safe(result_repr)
        else:
            field_val = getattr(result, f.attname)

            if isinstance(f.rel, models.ManyToOneRel):
                if field_val is not None:
                    result_repr = escape(getattr(result, f.name))
                else:
                    result_repr = EMPTY_CHANGELIST_VALUE
            # Dates and times are special: They're formatted in a certain way.
            elif isinstance(f, models.DateField) or isinstance(f, models.TimeField):
                if field_val:
                    (date_format, datetime_format, time_format) = get_date_formats()
                    if isinstance(f, models.DateTimeField):
                        result_repr = capfirst(dateformat.format(field_val, datetime_format))
                    elif isinstance(f, models.TimeField):
                        result_repr = capfirst(dateformat.time_format(field_val, time_format))
                    else:
                        result_repr = capfirst(dateformat.format(field_val, date_format))
                else:
                    result_repr = EMPTY_CHANGELIST_VALUE
            # Booleans are special: We use images.
            elif isinstance(f, models.BooleanField) or isinstance(f, models.NullBooleanField):
                result_repr = django_boolean_icon(field_val)
            # DecimalFields are special: Zero-pad the decimals.
            elif isinstance(f, models.DecimalField):
                if field_val is not None:
                    result_repr = ('%%.%sf' % f.decimal_places) % field_val
                else:
                    result_repr = EMPTY_CHANGELIST_VALUE
            # Fields with choices are special: Use the representation
            # of the choice.
            elif f.flatchoices:
                result_repr = dict(f.flatchoices).get(field_val, EMPTY_CHANGELIST_VALUE)
            else:
                result_repr = escape(field_val)
        if force_unicode(result_repr) == '':
            result_repr = mark_safe('&nbsp;')
        # If list_display_links not defined, add the link tag to the first field
        if (first and not cl.list_display_links) or field_name in cl.list_display_links:
            table_tag = {True:'th', False:'td'}[first]
            first = False
            url = cl.url_for_result(result)
            # Convert the pk to something that can be used in Javascript.
            # Problem cases are long ints (23L) and non-ASCII strings.
            if cl.to_field:
                attr = str(cl.to_field)
            else:
                attr = pk
            if DJANGO10_COMPAT: # see Django [9602]
                result_id = repr(force_unicode(getattr(result, attr)))[1:]
            else:
                value = result.serializable_value(attr)
                result_id = repr(force_unicode(value))[1:]
            yield mark_safe(u'<%s><a href="%s"%s>%s</a></%s>' % \
                (table_tag, url, (cl.is_popup and ' onclick="opener.dismissRelatedLookupPopup(window, %s); return false;"' % result_id or ''), conditional_escape(result_repr), table_tag))
        else:
            # By default the fields come from ModelAdmin.list_editable, but if we pull
            # the fields out of the form instead of list_editable custom admins
            # can provide fields on a per request basis
            result_repr = conditional_escape(result_repr)
            yield mark_safe(u'<td>%s</td>' % (result_repr))

        first = False
