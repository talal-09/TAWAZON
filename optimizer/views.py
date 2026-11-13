import logging

from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from academics.models import CourseRequest, Enrollment

from .forms import OptimizationForm, ScenarioForm
from .models import OptimizationRun, ProposedEnrollment
from .services.solver import diagnose_unassigned, solve_term


logger = logging.getLogger(__name__)


def _save_result(term, result, baseline_result=None, scenario_section=None, extra_seats=0):
    baseline_result = baseline_result or result
    enrolled_request_ids = set(Enrollment.objects.filter(request__term=term).values_list('request_id', flat=True))
    graduating_request_ids = set(CourseRequest.objects.filter(
        term=term, student__expected_to_graduate=True,
    ).values_list('pk', flat=True))
    before_assigned = len(enrolled_request_ids)
    total_requests = CourseRequest.objects.filter(term=term).count()
    baseline_ids = {item.request_id for item in baseline_result.assignments}
    result_ids = {item.request_id for item in result.assignments}
    seat_increases = {scenario_section.pk: extra_seats} if scenario_section else {}

    with transaction.atomic():
        run = OptimizationRun.objects.create(
            term=term,
            status=OptimizationRun.Status.COMPLETED,
            total_requests=total_requests,
            before_assigned=before_assigned,
            after_assigned=before_assigned + len(result_ids),
            scenario_section=scenario_section,
            extra_seats=extra_seats,
            baseline_after_assigned=before_assigned + len(baseline_ids),
            baseline_graduating_assigned=len((enrolled_request_ids | baseline_ids) & graduating_request_ids),
            after_graduating_assigned=len((enrolled_request_ids | result_ids) & graduating_request_ids),
            newly_assigned_count=len(result_ids - baseline_ids),
            unassigned_request_ids=result.unassigned_request_ids,
            unassigned_reasons=diagnose_unassigned(term, result, seat_increases),
        )
        ProposedEnrollment.objects.bulk_create([
            ProposedEnrollment(
                run=run,
                request_id=assignment.request_id,
                section_id=assignment.section_id,
            )
            for assignment in result.assignments
        ])
    return run


@staff_member_required
@require_http_methods(['GET', 'POST'])
def home(request):
    if not request.user.has_perm('optimizer.view_optimizationrun'):
        raise PermissionDenied
    can_run = request.user.has_perm('optimizer.add_optimizationrun')

    if request.method == 'POST':
        if not can_run:
            raise PermissionDenied
        action = request.POST.get('action', 'baseline')
        if action not in {'baseline', 'scenario'}:
            return HttpResponseBadRequest('نوع التشغيل غير صالح.')
        form = OptimizationForm(request.POST) if action == 'baseline' else OptimizationForm()
        scenario_form = ScenarioForm(request.POST) if action == 'scenario' else ScenarioForm()
        active_form = scenario_form if action == 'scenario' else form
        if active_form.is_valid():
            term = active_form.cleaned_data['term']
            try:
                baseline_result = solve_term(term)
                if action == 'scenario' and baseline_result.status in {'OPTIMAL', 'FEASIBLE'}:
                    section = scenario_form.cleaned_data['section']
                    extra_seats = scenario_form.cleaned_data['extra_seats']
                    result = solve_term(
                        term,
                        seat_increases={section.pk: extra_seats},
                        protected_request_ids={item.request_id for item in baseline_result.assignments},
                    )
                else:
                    section = None
                    extra_seats = 0
                    result = baseline_result
            except ValueError as exc:
                active_form.add_error(None, str(exc))
            else:
                if baseline_result.status not in {'OPTIMAL', 'FEASIBLE'} or result.status not in {'OPTIMAL', 'FEASIBLE'}:
                    logger.warning('Optimization returned %s/%s for term %s', baseline_result.status, result.status, term.pk)
                    active_form.add_error(None, 'تعذر حساب نتيجة التحسين. حاول مرة أخرى.')
                else:
                    run = _save_result(term, result, baseline_result, section, extra_seats)
                    return redirect(f"{reverse('optimizer:home')}?run={run.pk}")
    else:
        form = OptimizationForm()
        scenario_form = ScenarioForm()

    run_id = request.GET.get('run')
    if run_id is not None:
        if not run_id.isdecimal():
            raise Http404
        run = get_object_or_404(
            OptimizationRun.objects.select_related('term'),
            pk=run_id,
            status=OptimizationRun.Status.COMPLETED,
        )
    else:
        run = (
            OptimizationRun.objects.filter(status=OptimizationRun.Status.COMPLETED)
            .select_related('term')
            .first()
        )

    if run:
        if request.method == 'GET':
            form = OptimizationForm(initial={'term': run.term})
            scenario_form = ScenarioForm(initial={
                'term': run.term,
                'section': run.scenario_section,
                'extra_seats': run.extra_seats or None,
            })
        proposals = run.proposed_enrollments.select_related(
            'request__student', 'request__course', 'section__course'
        ).order_by('request__student__student_number', 'request__course__code')
        unassigned_requests = CourseRequest.objects.filter(
            pk__in=run.unassigned_request_ids
        ).select_related('student', 'course').order_by(
            '-student__expected_to_graduate', '-required_for_graduation',
            'student__student_number', 'course__code',
        )
        unassigned = [
            {'request': item, 'reason': run.unassigned_reasons.get(str(item.pk), 'السبب غير متاح')}
            for item in unassigned_requests
        ]
    else:
        proposals = []
        unassigned = []

    return render(request, 'optimizer/home.html', {
        'form': form,
        'scenario_form': scenario_form,
        'can_run': can_run,
        'run': run,
        'proposals': proposals,
        'unassigned': unassigned,
    })
