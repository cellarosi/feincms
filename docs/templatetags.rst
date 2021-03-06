.. _templatetags:

=============
Template tags
=============


General template tags
=====================

.. module:: feincms.templatetags.feincms_tags

To use the template tags described in this section, you need to load
the ``feincms_tags`` template tag library::

    {% load feincms_tags %}

.. function:: feincms_render_region:
.. function:: feincms_render_content:

   Some content types will need the request object to work properly. Contact forms
   will need to access POSTed data, a Google Map content type needs to use a
   different API key depending on the current domain etc. This means you should add
   ``django.core.context_processors.request`` to your ``TEMPLATE_CONTEXT_PROCESSORS``.

   These two template tags allow you to pass the request from the template to the
   content type. :func:`feincms_render_content` allows you to surround the individual
   content blocks with custom markup, :func:`feincms_render_region` simply concatenates
   the output of all content blocks::

       {% load feincms_tags %}

       {% feincms_render_region feincms_page "main" request %}

    or::

       {% load feincms_tags %}

       {% for content in feincms_page.content.main %}
           <div class="block">
               {% feincms_render_content content request %}
           </div>
       {% endfor %}

   Both template tags add the current rendering context to the ``render`` method
   call too. This means that you can access both the request and the current
   context inside your content type as follows::

       class MyContentType(models.Model):
           # class Meta etc...

           def render(self, **kwargs):
               request = kwargs.get('request')
               context = kwargs.get('context')


.. function:: feincms_frontend_editing:


Page module-specific template tags
==================================

.. module:: feincms.module.page.templatetags.feincms_page_tags

All page module-specific template tags are contained in ``feincms_page_tags``::

    {% load feincms_page_tags %}

.. function:: feincms_nav:

   Return a list of pages to be used for the navigation

   level: 1 = toplevel, 2 = sublevel, 3 = sub-sublevel
   depth: 1 = only one level, 2 = subpages too

   If you set depth to something else than 1, you might want to look into
   the ``tree_info`` template tag from the mptt_tags library.

   Example::

       {% load feincms_page_tags %}

       {% feincms_nav feincms_page level=2 depth=1 as sublevel %}
       {% for p in sublevel %}
           <a href="{{ p.get_absolute_url }}">{{ p.title }}</a>
       {% endfor %}

    This template tag has replaced ``feincms_navigation``, which used
    a hand-grown parser and had several bugs which were hard to fix without
    a complete rewrite.

.. function:: siblings_along_path_to:

   This is a filter designed to work in close conjuction with the
   ``feincms_navigation`` template tag describe above to build a
   navigation tree following the path to the current page.

   Example::

        {% feincms_navigation of feincms_page as navitems level=1,depth=3 %}
        {% with navitems|siblings_along_path_to:feincms_page as navtree %}
            {% recursetree navtree %}
                * {{ node.short_title }} <br>
                    {% if children %}
                        <div style="margin-left: 20px">{{ children }}</div>
                    {% endif %}
            {% endrecursetree %}
        {% endwith %}

   For helper function converting a tree of pages into an HTML
   representation please see the mptt_tags library's ``tree_info``
   and ``recursetree``.

.. function:: feincms_parentlink:

   Return a link to an ancestor of the passed page.

   You'd determine the link to the top level ancestor of the current page
   like this::

       {% load feincms_page_tags %}

       {% feincms_parentlink of feincms_page level=1 %}

   Please note that this is not the same as simply getting the URL of the
   parent of the current page.


.. function:: feincms_languagelinks:

   This template tag needs the translations extension.

   Arguments can be any combination of:

       * ``all`` or ``existing``: Return all languages or only those where a translation exists
       * ``excludecurrent``: Excludes the item in the current language from the list

   The default behavior is to return an entry for all languages including the
   current language.

   Example::

       {% load feincms_page_tags %}

       {% feincms_languagelinks for feincms_page as links all,excludecurrent %}
       {% for key, name, link in links %}
           <a href="{% if link %}{{ link }}{% else %}/{{ key }}/{% endif %}">{% trans name %}</a>
       {% endfor %}


.. function:: feincms_translatedpage:

   This template tag needs the translations extension.

   Returns the requested translation of the page if it exists. If the language
   argument is omitted the primary language will be returned (the first language
   specified in settings.LANGUAGES)::

       {% load feincms_page_tags %}

       {% feincms_translatedpage for feincms_page as feincms_transpage language=en %}
       {% feincms_translatedpage for feincms_page as originalpage %}
       {% feincms_translatedpage for some_page as translatedpage language=feincms_page.language %}

.. function:: feincms_translatedpage_or_base:

   This template tag needs the translations extensions.

   Similar in function and arguments to feincms_translatedpage, but if no translation
   for the requested language exists, the base language page will be returned::

       {% load feincms_page_tags %}

       {% feincms_translatedpage_or_base for some_page as some_transpage language=gr %}

.. function:: feincms_breadcrumbs:

   ::

       {% load feincms_page_tags %}

       {% feincms_breadcrumbs feincms_page %}

.. function:: is_parent_of:

   ::

       {% load feincms_page_tags %}

       {% if page1|is_parent_of:page2 %}
           page1 is a parent of page2
       {% endif %}

.. function:: is_equal_or_parent_of:

   ::

       {% load feincms_page_tags %}

       {% feincms_navigation of feincms_page as main level=1 %}
       {% for entry in main %}
           <a {% if entry|is_equal_or_parent_of:feincms_page %}class="mark"{% endif %}
               href="{{ entry.get_absolute_url }}">{{ entry.title }}</a>
       {% endfor %}

Application content template tags
=================================

.. module:: feincms.templatetags.applicationcontent_tags:

.. function:: app_reverse:

   Returns an absolute URL for applications integrated with ApplicationContent

   The tag mostly works the same way as Django's own {% url %} tag::

       {% load applicationcontent_tags %}
       {% app_reverse "mymodel_detail" "myapp.urls" arg1 arg2 %}

   or::

       {% load applicationcontent_tags %}
       {% app_reverse "mymodel_detail" "myapp.urls" name1=value1 name2=value2 %}

   The first argument is a path to a view. The second argument is the URLconf
   under which this app is known to the ApplicationContent.

   Other arguments are space-separated values that will be filled in place of
   positional and keyword arguments in the URL. Don't mix positional and
   keyword arguments.

   If you want to store the URL in a variable instead of showing it right away
   you can do so too::

       {% app_reverse "mymodel_detail" "myapp.urls" arg1 arg2 as url %}


.. function:: fragment:
.. function:: get_fragment:

   Don't use those, read up on :ref:`integration-applicationcontent-inheritance20`
   instead.
