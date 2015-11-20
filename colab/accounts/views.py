# encoding: utf-8
from collections import OrderedDict

import smtplib
import logging
import urlparse
import requests

from django import http
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.urlresolvers import reverse
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.db import IntegrityError
from django.db.models import Count
from django.http import Http404
from django.utils.decorators import method_decorator
from django.utils.translation import ugettext as _
from django.shortcuts import render, redirect
from django.views.generic import DetailView, UpdateView, View

from colab.search.utils import get_collaboration_data
from colab.accounts.models import (User, EmailAddress, EmailAddressValidation)
from colab.accounts.forms import (UserCreationForm, UserUpdateForm)
from colab.accounts.utils.email import send_verification_email


class UserProfileBaseMixin(object):
    model = get_user_model()
    slug_field = 'username'
    slug_url_kwarg = 'username'
    context_object_name = 'user_'


class UserProfileUpdateView(UserProfileBaseMixin, UpdateView):
    template_name = 'accounts/user_update_form.html'
    form_class = UserUpdateForm

    def get_success_url(self):
        return reverse('user_profile', kwargs={'username':
                                               self.object.username})

    def get_object(self, *args, **kwargs):
        obj = super(UserProfileUpdateView, self).get_object(*args, **kwargs)
        if self.request.user != obj and not self.request.user.is_superuser:
            raise PermissionDenied

        return obj


class UserProfileDetailView(UserProfileBaseMixin, DetailView):
    template_name = 'accounts/user_detail.html'

    def get_context_data(self, **kwargs):
        profile_user = self.object
        context = {}

        count_types = OrderedDict()

        logged_user = None
        if self.request.user.is_authenticated():
            logged_user = User.objects.get(username=self.request.user)

        collaborations, count_types_extras = get_collaboration_data(
            logged_user, profile_user)

        collaborations.sort(key=lambda elem: elem.modified, reverse=True)

        count_types.update(count_types_extras)

        context['type_count'] = count_types
        context['results'] = collaborations[:10]

		# TODO: implement these with superarchives
        #query = get_visible_threads(logged_user, profile_user)
        #context['emails'] = query.order_by('-received_time')[:10]

        #count_by = 'thread__mailinglist__name'
        #context['list_activity'] = dict(query.values_list(count_by)
        #                                .annotate(Count(count_by))
        #                                .order_by(count_by))

        context.update(kwargs)
        return super(UserProfileDetailView, self).get_context_data(**context)


class EmailView(View):

    http_method_names = [u'head', u'get', u'post', u'delete', u'update']

    def get(self, request, key):
        """Validate an email with the given key"""

        try:
            email_val = EmailAddressValidation.objects.get(validation_key=key)
        except EmailAddressValidation.DoesNotExist:
            messages.error(request, _('The email address you are trying to '
                                      'verify either has already been verified'
                                      ' or does not exist.'))
            return redirect('/')

        try:
            email = EmailAddress.objects.get(address=email_val.address)
        except EmailAddress.DoesNotExist:
            email = EmailAddress(address=email_val.address)

        if email.user and email.user.is_active:
            messages.error(request, _('The email address you are trying to '
                                      'verify is already an active email '
                                      'address.'))
            email_val.delete()
            return redirect('/')

        email.user = email_val.user
        email.save()
        email_val.delete()

        user = User.objects.get(username=email.user.username)
        user.is_active = True
        user.save()

        messages.success(request, _('Email address verified!'))
        return redirect('user_profile', username=email_val.user.username)

    @method_decorator(login_required)
    def post(self, request, key):
        """Create new email address that will wait for validation"""

        email = request.POST.get('email')
        user_id = request.POST.get('user')
        if not email:
            return http.HttpResponseBadRequest()

        try:
            EmailAddressValidation.objects.create(address=email,
                                                  user_id=user_id)
        except IntegrityError:
            # 409 Conflict
            #   duplicated entries
            #   email exist and it's waiting for validation
            return http.HttpResponse(status=409)

        return http.HttpResponse(status=201)

    @method_decorator(login_required)
    def delete(self, request, key):
        """Remove an email address, validated or not."""

        request.DELETE = http.QueryDict(request.body)
        email_addr = request.DELETE.get('email')
        user_id = request.DELETE.get('user')

        if not email_addr:
            return http.HttpResponseBadRequest()

        try:
            email = EmailAddressValidation.objects.get(address=email_addr,
                                                       user_id=user_id)
        except EmailAddressValidation.DoesNotExist:
            pass
        else:
            email.delete()
            return http.HttpResponse(status=204)

        try:
            email = EmailAddress.objects.get(address=email_addr,
                                             user_id=user_id)
        except EmailAddress.DoesNotExist:
            raise http.Http404

        email.user = None
        email.save()
        return http.HttpResponse(status=204)

    @method_decorator(login_required)
    def update(self, request, key):
        """Set an email address as primary address."""

        request.UPDATE = http.QueryDict(request.body)

        email_addr = request.UPDATE.get('email')
        user_id = request.UPDATE.get('user')
        if not email_addr:
            return http.HttpResponseBadRequest()

        try:
            email = EmailAddress.objects.get(address=email_addr,
                                             user_id=user_id)
        except EmailAddress.DoesNotExist:
            raise http.Http404

        email.user.email = email_addr
        email.user.save()
        return http.HttpResponse(status=204)


class EmailValidationView(View):

    http_method_names = [u'post']

    def post(self, request):
        email_addr = request.POST.get('email')
        user_id = request.POST.get('user')
        try:
            email = EmailAddressValidation.objects.get(address=email_addr,
                                                       user_id=user_id)
        except EmailAddressValidation.DoesNotExist:
            raise http.Http404

        try:
            send_verification_email(email_addr, email.user,
                                    email.validation_key)
        except smtplib.SMTPException:
            logging.exception('Error sending validation email')
            return http.HttpResponseServerError()

        return http.HttpResponse(status=204)


def signup(request):

    if request.user.is_authenticated():
        if not request.user.needs_update:
            return redirect('user_profile', username=request.user.username)

    if request.method == 'GET':
        user_form = UserCreationForm()
        # TODO: implement with superarchives plugin 
        # lists_form = ListsForm()

        return render(request, 'accounts/user_create_form.html',
                      {'user_form': user_form,})# 'lists_form': lists_form})

    user_form = UserCreationForm(request.POST)
    # TODO: do it with superarchives
    #lists_form = ListsForm(request.POST)

    if not user_form.is_valid():# or not lists_form.is_valid():
        return render(request, 'accounts/user_create_form.html',
                      {'user_form': user_form,})# 'lists_form': lists_form})

    user = user_form.save(commit=False)
    user.needs_update = False

    user.is_active = False
    user.save()

    email = EmailAddressValidation.create(user.email, user)

    location = reverse('email_view',
                       kwargs={'key': email.validation_key})
    verification_url = request.build_absolute_uri(location)
    EmailAddressValidation.verify_email(email, verification_url)

    # Check if the user's email have been used previously
    #   in the mainling lists to link the user to old messages
    email_addr, created = EmailAddress.objects.get_or_create(
        address=user.email)
    if created:
        email_addr.real_name = user.get_full_name()

    email_addr.user = user
    email_addr.save()

    # TODO: do it with superarchives
    #mailing_lists = lists_form.cleaned_data.get('lists')
    #mailman.update_subscription(user.email, mailing_lists)

    messages.success(request, _('Your profile has been created!'))

    return redirect('user_profile', username=user.username)


def password_changed(request):
    messages.success(request, _('Your password was changed.'))

    user = request.user

    return redirect('user_profile_update', username=user.username)


def password_reset_done_custom(request):
    msg = _(("We've emailed you instructions for setting "
             "your password. You should be receiving them shortly."))
    messages.success(request, msg)

    return redirect('home')


def password_reset_complete_custom(request):
    msg = _('Your password has been set. You may go ahead and log in now.')
    messages.success(request, msg)

    return redirect('home')


def myaccount_redirect(request, route):
    if not request.user.is_authenticated():
        raise Http404()

    url = '/'.join(('/account', request.user.username, route))

    return redirect(url)
