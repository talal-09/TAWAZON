import logging

from django.contrib import messages
from django.core.management import call_command
from django.core.exceptions import PermissionDenied
from django.db.models.deletion import ProtectedError
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.db import transaction
from django.db.models import Count, Sum
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .forms import CourseForm
from .models import AcademicTerm, Course, CourseRequest, Section
from optimizer.models import OptimizationRun
from optimizer.services.results import save_result
from optimizer.services.solver import recommend_seat_increases, solve_term

logger = logging.getLogger(__name__)


def _course_access(user, permission):
    return user.is_authenticated and user.is_staff and user.has_perm(f'academics.{permission}_course')


def _course_context(request):
    can_add = _course_access(request.user, 'add')
    can_edit = _course_access(request.user, 'change')
    can_delete = _course_access(request.user, 'delete')
    return {
        'can_add_course': can_add,
        'can_edit_course': can_edit,
        'can_delete_course': can_delete,
        'managed_courses': (
            Course.objects.order_by('code')
            if can_add or can_edit or can_delete else Course.objects.none()
        ),
    }


def _require_course_access(user, permission):
    if not _course_access(user, permission):
        raise PermissionDenied


def _course_is_linked(course):
    return (
        course.sections.exists() or course.requests.exists()
        or course.opens_courses.exists() or course.students_completed.exists()
    )


@require_http_methods(['GET', 'POST'])
def course_create(request):
    _require_course_access(request.user, 'add')
    form = CourseForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'أُضيف المقرر. أضف شعبة وطلبات تسجيل ليظهر أثره في التحسين.')
        return redirect(reverse('academics:home') + '#course-catalog')
    return render(request, 'academics/course_form.html', {'form': form, 'heading': 'إضافة مقرر'})


@require_http_methods(['GET', 'POST'])
def course_edit(request, course_id):
    _require_course_access(request.user, 'change')
    course = get_object_or_404(Course, pk=course_id)
    form = CourseForm(request.POST or None, instance=course)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'حُفظ تعديل المقرر.')
        return redirect(reverse('academics:home') + '#course-catalog')
    return render(request, 'academics/course_form.html', {
        'form': form, 'heading': 'تعديل مقرر', 'course': course,
    })


@require_http_methods(['GET', 'POST'])
def course_delete(request, course_id):
    _require_course_access(request.user, 'delete')
    course = get_object_or_404(Course, pk=course_id)
    linked = _course_is_linked(course)
    if request.method == 'POST':
        if linked:
            messages.error(request, 'لا يمكن حذف مقرر مرتبط بشعب أو طلبات أو متطلبات أكاديمية.')
        else:
            try:
                course.delete()
            except ProtectedError:
                logger.warning('Course %s became protected during deletion', course_id)
                messages.error(request, 'تعذر حذف المقرر لأنه مرتبط ببيانات أخرى.')
            else:
                messages.success(request, 'حُذف المقرر.')
        return redirect(reverse('academics:home') + '#course-catalog')
    return render(request, 'academics/course_confirm_delete.html', {
        'course': course, 'linked': linked,
    })


@require_http_methods(['GET', 'POST'])
def home(request):
    can_reset = (
        request.user.is_authenticated and request.user.is_staff
        and request.user.has_perm('academics.add_academicterm')
        and request.user.has_perm('optimizer.add_optimizationrun')
        and request.user.has_perm('optimizer.view_optimizationrun')
    )
    if request.method == 'POST':
        if not can_reset:
            return HttpResponseForbidden('إعادة ضبط المثال تتطلب صلاحية الإدارة.')
        if request.POST.get('action') != 'reset_example':
            return HttpResponseForbidden('الإجراء غير صالح.')
        try:
            with transaction.atomic():
                name = f"فصل توازن المعاد {timezone.now():%Y%m%d%H%M%S%f}"
                call_command('seed_example', large=True, term_name=name, verbosity=0)
                term = AcademicTerm.objects.get(name=name)
                baseline = solve_term(term)
                if baseline.status not in {'OPTIMAL', 'FEASIBLE'}:
                    raise ValueError(f'تعذر حساب خط الأساس: {baseline.status}')
                section = Section.objects.get(term=term, course__code='PROJ499', code='A')
                scenario = solve_term(
                    term, seat_increases={section.pk: 10},
                    protected_request_ids={item.request_id for item in baseline.assignments},
                )
                if scenario.status not in {'OPTIMAL', 'FEASIBLE'}:
                    raise ValueError(f'تعذر حساب السيناريو: {scenario.status}')
                save_result(
                    term, scenario, baseline_result=baseline,
                    scenario_type=OptimizationRun.Scenario.SEATS,
                    scenario_section=section, extra_seats=10,
                    scenario_settings={'section': str(section), 'extra_seats': 10},
                    recommendations=recommend_seat_increases(term, baseline),
                )
        except (ValueError, AcademicTerm.DoesNotExist, Section.DoesNotExist):
            logger.exception('Example reset failed')
            messages.error(request, 'تعذرت إعادة ضبط المثال. لم تُحفظ نسخة غير مكتملة.')
        else:
            messages.success(request, 'أُنشئت نسخة جديدة من بيانات المثال، وحُفظت نتيجة محسوبة لها.')
        return redirect('academics:home')
    showcase = OptimizationRun.objects.filter(
        status=OptimizationRun.Status.COMPLETED,
        term__is_example=True,
        scenario_type=OptimizationRun.Scenario.SEATS,
    ).select_related('term').first()
    term = showcase.term if showcase else AcademicTerm.objects.filter(is_example=True).order_by('-id').first()
    if not term:
        return render(request, 'academics/home.html', {
            'term': None, 'can_reset': can_reset, **_course_context(request),
        })
    demand = list(CourseRequest.objects.filter(term=term).values(
        'course_id', 'course__code', 'course__title',
    ).annotate(requests=Count('id')).order_by('-requests', 'course__code'))
    seats = dict(Section.objects.filter(term=term).values('course_id').annotate(
        capacity=Sum('capacity'),
    ).values_list('course_id', 'capacity'))
    for row in demand:
        row['capacity'] = seats.get(row['course_id'], 0)
        row['gap'] = max(0, row['requests'] - row['capacity'])
    return render(request, 'academics/home.html', {
        'term': term,
        'students_count': CourseRequest.objects.filter(term=term).values('student_id').distinct().count(),
        'graduating_students_count': CourseRequest.objects.filter(
            term=term, student__expected_to_graduate=True,
        ).values('student_id').distinct().count(),
        'requests_count': sum(row['requests'] for row in demand),
        'sections_count': Section.objects.filter(term=term).count(),
        'capacity_count': sum(seats.values()),
        'course_demand': demand,
        'can_reset': can_reset,
        **_course_context(request),
    })
