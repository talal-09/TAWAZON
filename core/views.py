from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.db.models import Sum
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST
from django.shortcuts import render

from academics.models import Section
from optimizer.models import OptimizationRun


def home(request):
    showcase = OptimizationRun.objects.filter(
        status=OptimizationRun.Status.COMPLETED,
        term__is_example=True,
        scenario_type=OptimizationRun.Scenario.SEATS,
    ).select_related('term').first()
    chart = None
    if showcase:
        before_seats = showcase.scenario_settings.get('baseline_capacity')
        if before_seats is None:
            before_seats = Section.objects.filter(term=showcase.term).aggregate(
                total=Sum('capacity'),
            )['total'] or 0
        after_seats = before_seats + showcase.extra_seats
        scale = max(showcase.total_requests, before_seats, after_seats, 1)
        chart = {
            'before_requests': showcase.total_requests,
            'before_seats': before_seats,
            'after_requests': showcase.after_assigned,
            'after_seats': after_seats,
            'before_request_rate': round(showcase.total_requests * 100 / scale),
            'before_seat_rate': round(before_seats * 100 / scale),
            'remaining_requests': max(0, showcase.total_requests - showcase.after_assigned),
        }
    return render(request, 'core/home.html', {'showcase': showcase, 'chart': chart})


def _safe_next(request):
    target = request.POST.get('next') or request.GET.get('next')
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return target
    return 'optimizer:home'


@require_http_methods(['GET', 'POST'])
def register(request):
    if request.user.is_authenticated:
        return redirect('core:home')
    form = UserCreationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        login(request, user)
        return redirect('optimizer:home')
    return render(request, 'core/account.html', {'form': form, 'mode': 'register'})


@require_http_methods(['GET', 'POST'])
def sign_in(request):
    if request.user.is_authenticated:
        return redirect('core:home')
    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == 'POST' and form.is_valid():
        login(request, form.get_user())
        return redirect(_safe_next(request))
    return render(request, 'core/account.html', {
        'form': form, 'mode': 'login', 'next': _safe_next(request),
    })


@require_POST
def sign_out(request):
    logout(request)
    return redirect('core:home')
