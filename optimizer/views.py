import csv
import logging

from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from academics.models import CourseRequest

from .forms import MoveTimeForm, NewSectionForm, OptimizationForm, ScenarioForm
from .models import OptimizationRun
from .services.results import fingerprint_term, save_result
from .services.solver import recommend_seat_increases, solve_term

logger = logging.getLogger(__name__)

FORM_CLASSES = {
    'baseline': OptimizationForm,
    'scenario': ScenarioForm,
    'new_section': NewSectionForm,
    'move_time': MoveTimeForm,
}


def _can_view_details(user):
    return user.is_authenticated and user.is_staff and user.has_perm('optimizer.view_optimizationrun')


def _scenario_data(action, cleaned):
    """Return solver inputs and a JSON-safe description of one scenario."""
    if action == 'scenario':
        section = cleaned['section']
        seats = cleaned['extra_seats']
        return {
            'scenario_type': OptimizationRun.Scenario.SEATS,
            'scenario_section': section,
            'extra_seats': seats,
            'seat_increases': {section.pk: seats},
            'scenario_settings': {'section_id': section.pk, 'extra_seats': seats},
        }
    if action == 'new_section':
        course = cleaned['course']
        slot = {
            'weekday': int(cleaned['weekday']),
            'start_time': cleaned['start_time'],
            'end_time': cleaned['end_time'],
        }
        return {
            'scenario_type': OptimizationRun.Scenario.NEW_SECTION,
            'new_section': {
                'course_id': course.pk, 'capacity': cleaned['capacity'],
                'meetings': [slot],
            },
            'scenario_settings': {
                'course': course.title, 'course_id': course.pk,
                'capacity': cleaned['capacity'], 'weekday': slot['weekday'],
                'start_time': slot['start_time'].strftime('%H:%M'),
                'end_time': slot['end_time'].strftime('%H:%M'),
            },
        }
    if action == 'move_time':
        section = cleaned['section']
        slot = {
            'weekday': int(cleaned['weekday']),
            'start_time': cleaned['start_time'],
            'end_time': cleaned['end_time'],
        }
        return {
            'scenario_type': OptimizationRun.Scenario.MOVE_TIME,
            'scenario_section': section,
            'meeting_changes': {section.pk: [slot]},
            'scenario_settings': {
                'section_id': section.pk, 'section': str(section),
                'weekday': slot['weekday'],
                'start_time': slot['start_time'].strftime('%H:%M'),
                'end_time': slot['end_time'].strftime('%H:%M'),
            },
        }
    return {'scenario_type': OptimizationRun.Scenario.BASELINE}


def _legacy_rows(run):
    proposals = [
        {
            'student_name': item.request.student.full_name,
            'student_number': item.request.student.student_number,
            'course_code': item.request.course.code,
            'course_title': item.request.course.title,
            'section_code': item.section.code if item.section else item.virtual_section_label,
            'graduating': item.request.student.expected_to_graduate,
            'required': item.request.required_for_graduation,
        }
        for item in run.proposed_enrollments.select_related(
            'request__student', 'request__course', 'section'
        ).order_by('request__student__student_number', 'request__course__code')
    ]
    requests = CourseRequest.objects.filter(pk__in=run.unassigned_request_ids).select_related('student', 'course')
    unassigned = [
        {
            'student_name': item.student.full_name,
            'student_number': item.student.student_number,
            'course_code': item.course.code,
            'course_title': item.course.title,
            'graduating': item.student.expected_to_graduate,
            'required': item.required_for_graduation,
            'reason': run.unassigned_reasons.get(str(item.pk), 'غير محدد'),
        }
        for item in requests
    ]
    return proposals, unassigned


@require_http_methods(['GET', 'POST'])
def home(request):
    can_view_details = _can_view_details(request.user)
    can_run = can_view_details and request.user.has_perm('optimizer.add_optimizationrun')
    forms = {key: form_class() for key, form_class in FORM_CLASSES.items()}

    if request.method == 'POST':
        if not can_run:
            raise PermissionDenied
        action = request.POST.get('action', 'baseline')
        if action not in FORM_CLASSES:
            return HttpResponseBadRequest('نوع التشغيل غير صالح.')
        forms[action] = FORM_CLASSES[action](request.POST)
        active_form = forms[action]
        if active_form.is_valid():
            term = active_form.cleaned_data['term']
            scenario = _scenario_data(action, active_form.cleaned_data)
            try:
                baseline = solve_term(term)
                if baseline.status not in {'OPTIMAL', 'FEASIBLE'}:
                    logger.warning('Baseline solver returned %s for term %s', baseline.status, term.pk)
                    active_form.add_error(None, 'تعذر حساب التوزيع. حاول مرة أخرى.')
                else:
                    result = baseline if action == 'baseline' else solve_term(
                        term,
                        seat_increases=scenario.get('seat_increases'),
                        new_section=scenario.get('new_section'),
                        meeting_changes=scenario.get('meeting_changes'),
                        protected_request_ids={item.request_id for item in baseline.assignments},
                    )
                    if result.status not in {'OPTIMAL', 'FEASIBLE'}:
                        logger.warning('Scenario solver returned %s for term %s', result.status, term.pk)
                        active_form.add_error(None, 'تعذر حساب السيناريو. حاول مرة أخرى.')
                    else:
                        recommendations = recommend_seat_increases(term, baseline)
                        run = save_result(
                            term, result, baseline_result=baseline,
                            scenario_type=scenario['scenario_type'],
                            scenario_section=scenario.get('scenario_section'),
                            extra_seats=scenario.get('extra_seats', 0),
                            scenario_settings=scenario.get('scenario_settings'),
                            recommendations=recommendations,
                            new_section=scenario.get('new_section'),
                            meeting_changes=scenario.get('meeting_changes'),
                        )
                        return redirect(f"{reverse('optimizer:home')}?run={run.pk}")
            except ValueError as exc:
                active_form.add_error(None, str(exc))

    runs = OptimizationRun.objects.filter(status=OptimizationRun.Status.COMPLETED).select_related(
        'term', 'scenario_section__course'
    )
    if not can_view_details:
        runs = runs.filter(term__is_example=True)
    run_id = request.GET.get('run')
    if run_id is not None:
        if not run_id.isdecimal():
            raise Http404
        run = get_object_or_404(runs, pk=run_id)
    else:
        run = runs.first()

    if run:
        if request.method == 'GET':
            initial = {'term': run.term}
            forms = {key: form_class(initial=initial) for key, form_class in FORM_CLASSES.items()}
            if run.scenario_section_id:
                forms['scenario'] = ScenarioForm(initial={
                    **initial, 'section': run.scenario_section, 'extra_seats': run.extra_seats or None,
                })
        before = run.baseline_after_assigned if run.scenario_type != OptimizationRun.Scenario.BASELINE else run.before_assigned
        before_rate = round(before * 100 / run.total_requests) if run.total_requests else 0
        after_rate = round(run.after_assigned * 100 / run.total_requests) if run.total_requests else 0
        impact_count = run.newly_assigned_count if run.scenario_type != OptimizationRun.Scenario.BASELINE else run.after_assigned - run.before_assigned
        if can_view_details:
            proposals, unassigned = (
                (run.proposal_snapshot, run.unassigned_snapshot)
                if run.data_fingerprint else _legacy_rows(run)
            )
        else:
            proposals = unassigned = []
        graduating_requests_count = (
            sum(row.get('graduating', False) for row in run.proposal_snapshot + run.unassigned_snapshot)
            if run.data_fingerprint else CourseRequest.objects.filter(
                term=run.term, student__expected_to_graduate=True,
            ).count()
        )
        if run.data_fingerprint:
            unassigned_students = {
                row['student_number'] for row in run.unassigned_snapshot
            }
            unassigned_graduating_students = {
                row['student_number'] for row in run.unassigned_snapshot
                if row.get('graduating')
            }
            unassigned_student_count = len(unassigned_students)
            unassigned_graduating_student_count = len(unassigned_graduating_students)
            data_changed = fingerprint_term(run.term) != run.data_fingerprint
        else:
            remaining_requests = CourseRequest.objects.filter(
                pk__in=run.unassigned_request_ids,
            )
            unassigned_student_count = remaining_requests.values('student_id').distinct().count()
            unassigned_graduating_student_count = remaining_requests.filter(
                student__expected_to_graduate=True,
            ).values('student_id').distinct().count()
            data_changed = False
    else:
        before_rate = after_rate = impact_count = 0
        proposals = unassigned = []
        graduating_requests_count = 0
        unassigned_student_count = unassigned_graduating_student_count = 0
        data_changed = False

    return render(request, 'optimizer/home.html', {
        'form': forms['baseline'],
        'scenario_form': forms['scenario'],
        'new_section_form': forms['new_section'],
        'move_time_form': forms['move_time'],
        'can_run': can_run,
        'can_view_details': can_view_details,
        'run': run,
        'proposals': proposals,
        'unassigned': unassigned,
        'before_rate': before_rate,
        'after_rate': after_rate,
        'impact_count': impact_count,
        'graduating_requests_count': graduating_requests_count,
        'unassigned_student_count': unassigned_student_count,
        'unassigned_graduating_student_count': unassigned_graduating_student_count,
        'data_changed': data_changed,
        'scenario_label': run.get_scenario_type_display() if run else '',
        'term_label': run.scenario_settings.get('term_name', run.term.name) if run else '',
        'unassigned_count': len(run.unassigned_request_ids) if run else 0,
    })


def _safe_csv(value):
    value = str(value or '')
    return f"'{value}" if value and value[0] in '=+-@\t\r\n' else value


@staff_member_required
def export_csv(request, run_id):
    if not request.user.has_perm('optimizer.view_optimizationrun'):
        raise PermissionDenied
    run = get_object_or_404(OptimizationRun, pk=run_id, status=OptimizationRun.Status.COMPLETED)
    proposals, unassigned = (
        (run.proposal_snapshot, run.unassigned_snapshot)
        if run.data_fingerprint else _legacy_rows(run)
    )
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="tawazon-run-{run.pk}.csv"'
    response.write('\ufeff')
    writer = csv.writer(response)
    writer.writerow(['الحالة', 'الطالب', 'الرقم الجامعي', 'المقرر', 'الشعبة', 'الأولوية', 'تفسير محتمل'])
    for status, rows in (('مقترح', proposals), ('دون مقعد', unassigned)):
        for row in rows:
            priority = 'متوقع تخرجه' if row.get('graduating') else (
                'مطلوب للتخرج' if row.get('required') else 'عادية'
            )
            writer.writerow([
                status, _safe_csv(row.get('student_name')), _safe_csv(row.get('student_number')),
                _safe_csv(row.get('course_title')), _safe_csv(row.get('section_code')),
                priority, _safe_csv(row.get('reason')),
            ])
    return response
