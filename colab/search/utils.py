import importlib
import inspect

from collections import OrderedDict

from django.core.cache import cache
from django.utils.translation import ugettext as _
from django.conf import settings
from django.db.models import Q as Condition

from colab.super_archives.models import Thread, Message
from colab.proxy.utils.models import Collaboration
from colab.accounts.utils import mailman


def get_visible_threads_queryset(logged_user):
    queryset = Thread.objects
    lists_for_user = []
    if logged_user:
        lists_for_user = mailman.get_user_mailinglists(logged_user)

    user_lists = Condition(mailinglist__name__in=lists_for_user)
    public_lists = Condition(mailinglist__is_private=False)
    queryset = Thread.objects.filter(user_lists | public_lists)

    return queryset


def get_visible_threads(logged_user, filter_by_user=None):
    thread_qs = get_visible_threads_queryset(logged_user)
    if filter_by_user:
        message_qs = Message.objects.filter(thread__in=thread_qs)
        messages = message_qs.filter(
            from_address__user__pk=filter_by_user.pk)
    else:
        latest_threads = thread_qs.all()
        messages = [t.latest_message for t in latest_threads]

    return messages


def get_collaboration_data(logged_user, filter_by_user=None):
    username = getattr(filter_by_user, 'username', '')
    cache_key = 'home_chart-{}'.format(username)
    count_types = cache.get(cache_key)

    latest_results = []
    populate_count_types = False

    if count_types is None:
        populate_count_types = True
        count_types = OrderedDict()
        visible_threads = get_visible_threads(logged_user, filter_by_user)
        count_types[_('Emails')] = len(visible_threads)

    messages = get_visible_threads(logged_user, filter_by_user)

    latest_results.extend(messages)

    app_names = settings.PROXIED_APPS.keys()

    for app_name in app_names:
        module = importlib \
            .import_module('colab.proxy.{}.models'.format(app_name))

        for module_item_name in dir(module):
            module_item = getattr(module, module_item_name)
            if not inspect.isclass(module_item):
                continue
            if not issubclass(module_item, Collaboration):
                continue
            if module_item == Collaboration:
                continue

            queryset = module_item.objects

            if filter_by_user:
                elements = queryset.filter(
                    user__username=filter_by_user)
            else:
                elements = queryset.all()

            latest_results.extend(elements)
            elements_count = elements.count()

            if elements_count > 1:
                verbose_name = module_item._meta.verbose_name_plural.title()
            else:
                verbose_name = module_item._meta.verbose_name.title()

            if populate_count_types:
                count_types[verbose_name] = elements_count

    if populate_count_types:
        cache.set(cache_key, count_types, 30)

    return latest_results, count_types
