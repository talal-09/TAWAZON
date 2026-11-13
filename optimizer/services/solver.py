from collections import Counter, defaultdict
from dataclasses import dataclass

from ortools.sat.python import cp_model

from academics.models import CourseRequest, Enrollment, Section


@dataclass(frozen=True)
class Assignment:
    request_id: int
    section_id: int


@dataclass(frozen=True)
class SolverResult:
    status: str
    assignments: list[Assignment]
    unassigned_request_ids: list[int]
    objective_value: float


def sections_conflict(first_section, second_section) -> bool:
    """Return True when two sections overlap on the same weekday."""
    first_meetings = list(first_section.meeting_times.all())
    second_meetings = list(second_section.meeting_times.all())

    for first in first_meetings:
        for second in second_meetings:
            same_day = first.weekday == second.weekday
            overlaps = (
                first.start_time < second.end_time
                and second.start_time < first.end_time
            )

            if same_day and overlaps:
                return True

    return False


def request_priority(request: CourseRequest) -> int:
    """Give higher priority to graduation-sensitive requests."""
    priority = 1

    if request.required_for_graduation:
        priority += 20

    if request.student.expected_to_graduate:
        priority += 100

    return priority


def diagnose_unassigned(term, result: SolverResult, seat_increases=None) -> dict[str, str]:
    """Explain why each request has no seat in the computed assignment."""
    seat_increases = seat_increases or {}
    if not result.unassigned_request_ids:
        return {}

    requests = list(CourseRequest.objects.filter(
        term=term,
        pk__in=result.unassigned_request_ids,
    ).select_related("student"))
    sections = list(Section.objects.filter(term=term).prefetch_related("meeting_times"))
    current_enrollments = list(Enrollment.objects.filter(
        request__term=term,
    ).select_related("request", "section").prefetch_related("section__meeting_times"))

    sections_by_id = {section.pk: section for section in sections}
    sections_by_course = defaultdict(list)
    for section in sections:
        sections_by_course[section.course_id].append(section)

    occupied_seats = Counter(enrollment.section_id for enrollment in current_enrollments)
    busy_sections = defaultdict(list)
    for enrollment in current_enrollments:
        busy_sections[enrollment.request.student_id].append(enrollment.section)

    assigned_requests = CourseRequest.objects.filter(
        pk__in=[assignment.request_id for assignment in result.assignments]
    ).values_list("pk", "student_id")
    student_by_request = dict(assigned_requests)
    for assignment in result.assignments:
        occupied_seats[assignment.section_id] += 1
        busy_sections[student_by_request[assignment.request_id]].append(
            sections_by_id[assignment.section_id]
        )

    reasons = {}
    for request in requests:
        options = sections_by_course[request.course_id]
        if not options:
            reason = "لا توجد شعبة لهذا المقرر"
        else:
            has_full = False
            has_conflict = False
            has_free_option = False
            for section in options:
                if occupied_seats[section.pk] >= section.capacity + seat_increases.get(section.pk, 0):
                    has_full = True
                elif any(sections_conflict(section, busy) for busy in busy_sections[request.student_id]):
                    has_conflict = True
                else:
                    has_free_option = True

            if has_free_option:
                reason = "تعذر التوزيع ضمن القيود والأولويات الحالية"
            elif has_full and has_conflict:
                reason = "امتلاء بعض الشعب وتعارض مواعيد البقية"
            elif has_full:
                reason = "جميع الشعب ممتلئة"
            else:
                reason = "جميع الشعب المتاحة تتعارض مع جدول الطالب"
        reasons[str(request.pk)] = reason

    return reasons


def solve_term(term, time_limit_seconds: int = 10, seat_increases=None, protected_request_ids=None) -> SolverResult:
    """Find the best feasible section assignment for one academic term."""
    if time_limit_seconds <= 0:
        raise ValueError("يجب أن تكون مهلة الحل أكبر من صفر.")
    seat_increases = seat_increases or {}
    protected_request_ids = set(protected_request_ids or ())
    if any(not isinstance(seats, int) or seats < 0 for seats in seat_increases.values()):
        raise ValueError("عدد المقاعد الإضافية يجب أن يكون غير سالب.")

    requests = list(
        CourseRequest.objects.filter(
            term=term,
            enrollment__isnull=True,
        ).select_related("student", "course")
    )
    if protected_request_ids - {request.pk for request in requests}:
        raise ValueError("طلبات الحماية لا تتبع الفصل أو هي مسجلة مسبقًا.")

    sections = list(
        Section.objects.filter(term=term)
        .select_related("course")
        .prefetch_related("meeting_times")
    )
    if set(seat_increases) - {section.pk for section in sections}:
        raise ValueError("شعبة السيناريو لا تتبع الفصل الدراسي المحدد.")

    if any(not section.meeting_times.all() for section in sections):
        raise ValueError("لا يمكن تشغيل التحسين: توجد شعبة بلا موعد محاضرة.")

    current_enrollments = list(
        Enrollment.objects.filter(request__term=term)
        .select_related("request__student", "section")
        .prefetch_related("section__meeting_times")
    )

    model = cp_model.CpModel()

    sections_by_course = defaultdict(list)
    for section in sections:
        sections_by_course[section.course_id].append(section)

    occupied_seats = Counter(
        enrollment.section_id for enrollment in current_enrollments
    )

    current_sections_by_student = defaultdict(list)
    for enrollment in current_enrollments:
        current_sections_by_student[
            enrollment.request.student_id
        ].append(enrollment.section)

    variables = {}
    options_by_student = defaultdict(list)

    for request in requests:
        for section in sections_by_course[request.course_id]:
            variable = model.NewBoolVar(
                f"request_{request.id}_section_{section.id}"
            )

            variables[(request.id, section.id)] = variable
            options_by_student[request.student_id].append(
                (request, section, variable)
            )

            existing_sections = current_sections_by_student[
                request.student_id
            ]

            if any(
                sections_conflict(section, existing_section)
                for existing_section in existing_sections
            ):
                model.Add(variable == 0)

    # Each request can receive no more than one section.
    for request in requests:
        request_variables = [
            variable
            for (request_id, _), variable in variables.items()
            if request_id == request.id
        ]

        if request_variables:
            model.Add(sum(request_variables) <= 1)
            if request.pk in protected_request_ids:
                model.Add(sum(request_variables) == 1)
        elif request.pk in protected_request_ids:
            raise ValueError("لا توجد شعبة لطلب مطلوب الحفاظ عليه.")

    # Section capacity must include students already enrolled.
    for section in sections:
        available_seats = max(
            section.capacity + seat_increases.get(section.pk, 0) - occupied_seats[section.id],
            0,
        )

        section_variables = [
            variable
            for (_, section_id), variable in variables.items()
            if section_id == section.id
        ]

        if section_variables:
            model.Add(sum(section_variables) <= available_seats)

    # A student cannot receive two overlapping sections.
    for student_options in options_by_student.values():
        for first_index, first_option in enumerate(student_options):
            first_request, first_section, first_variable = first_option

            for second_option in student_options[first_index + 1:]:
                second_request, second_section, second_variable = second_option

                if first_request.id == second_request.id:
                    continue

                if sections_conflict(first_section, second_section):
                    model.Add(first_variable + second_variable <= 1)

    objective_terms = []

    for request in requests:
        priority = request_priority(request)

        for section in sections_by_course[request.course_id]:
            variable = variables.get((request.id, section.id))

            if variable is not None:
                objective_terms.append(priority * variable)

    if objective_terms:
        model.Maximize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_seconds
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 42

    status_code = solver.Solve(model)
    status_name = solver.StatusName(status_code)

    successful_statuses = {
        cp_model.OPTIMAL,
        cp_model.FEASIBLE,
    }

    if status_code not in successful_statuses:
        return SolverResult(
            status=status_name,
            assignments=[],
            unassigned_request_ids=[request.id for request in requests],
            objective_value=0,
        )

    assignments = []
    assigned_request_ids = set()

    for (request_id, section_id), variable in variables.items():
        if solver.Value(variable) == 1:
            assignments.append(
                Assignment(
                    request_id=request_id,
                    section_id=section_id,
                )
            )
            assigned_request_ids.add(request_id)

    unassigned_request_ids = [
        request.id
        for request in requests
        if request.id not in assigned_request_ids
    ]

    return SolverResult(
        status=status_name,
        assignments=assignments,
        unassigned_request_ids=unassigned_request_ids,
        objective_value=solver.ObjectiveValue(),
    )
