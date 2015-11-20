from django.conf import settings
from django.shortcuts import render
from django.http import HttpResponse, Http404

from colab.search.utils import get_collaboration_data
from colab.accounts.models import User


def dashboard(request):
    """Dashboard page"""

    user = None
    if request.user.is_authenticated():
        user = User.objects.get(username=request.user)

    latest_results, count_types = get_collaboration_data(user)
    latest_results.sort(key=lambda elem: elem.modified, reverse=True)

    context = {
        'type_count': count_types,
        'latest_results': latest_results[:6],
    }
    return render(request, 'home.html', context)


def robots(request):
    if getattr(settings, 'ROBOTS_NOINDEX', False):
        return HttpResponse('User-agent: *\nDisallow: /',
                            content_type='text/plain')

    raise Http404
