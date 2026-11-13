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


def solve_term(term, time_limit_seconds: int = 10) -> SolverResult:
    """Find the best feasible section assignment for one academic term."""
    if time_limit_seconds <= 0:
        raise ValueError("يجب أن تكون مهلة الحل أكبر من صفر.")

    requests = list(
        CourseRequest.objects.filter(
            term=term,
            enrollment__isnull=True,
        ).select_related("student", "course")
    )

    sections = list(
        Section.objects.filter(term=term)
        .select_related("course")
        .prefetch_related("meeting_times")
    )

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

    # Section capacity must include students already enrolled.
    for section in sections:
        available_seats = max(
            section.capacity - occupied_seats[section.id],
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