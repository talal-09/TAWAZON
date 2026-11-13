"""Course assignment with explicit academic priorities and isolated scenarios."""

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import time

from ortools.sat.python import cp_model

from academics.models import CourseRequest, Enrollment, Section

POLICY_VERSION = "2.0"


@dataclass(frozen=True)
class MeetingSlot:
    weekday: int
    start_time: time
    end_time: time


@dataclass(frozen=True)
class SectionOption:
    id: int
    course_id: int
    code: str
    capacity: int
    meetings: tuple[MeetingSlot, ...]
    virtual: bool = False


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
    covered_student_ids: list[int]
    best_bound: float


def sections_conflict(first: SectionOption, second: SectionOption) -> bool:
    return any(
        a.weekday == b.weekday
        and a.start_time < b.end_time
        and b.start_time < a.end_time
        for a in first.meetings for b in second.meetings
    )


def _slot(value) -> MeetingSlot:
    if isinstance(value, MeetingSlot):
        slot = value
    else:
        slot = MeetingSlot(value["weekday"], value["start_time"], value["end_time"])
    if slot.weekday not in range(7):
        raise ValueError("يوم المحاضرة غير صالح.")
    if slot.start_time >= slot.end_time:
        raise ValueError("وقت نهاية المحاضرة يجب أن يكون بعد بدايتها.")
    return slot


def _sections(term, seat_increases, new_section, meeting_changes):
    sections = list(
        Section.objects.filter(term=term).select_related("course").prefetch_related("meeting_times")
    )
    ids = {section.pk for section in sections}
    if set(seat_increases) - ids or set(meeting_changes) - ids:
        raise ValueError("شعبة السيناريو لا تتبع الفصل الدراسي المحدد.")
    if any(not isinstance(seats, int) or seats < 0 for seats in seat_increases.values()):
        raise ValueError("عدد المقاعد الإضافية يجب أن يكون غير سالب.")

    options = []
    for section in sections:
        meetings = tuple(
            MeetingSlot(item.weekday, item.start_time, item.end_time)
            for item in section.meeting_times.all()
        )
        if not meetings:
            raise ValueError("لا يمكن تشغيل التحسين: توجد شعبة بلا موعد محاضرة.")
        if section.pk in meeting_changes:
            meetings = tuple(_slot(item) for item in meeting_changes[section.pk])
            if not meetings:
                raise ValueError("يجب تحديد موعد واحد على الأقل للشعبة.")
        options.append(SectionOption(
            section.pk, section.course_id, section.code,
            section.capacity + seat_increases.get(section.pk, 0), meetings,
        ))

    if new_section:
        course_id = new_section["course_id"]
        if not CourseRequest.objects.filter(term=term, course_id=course_id).exists():
            raise ValueError("المقرر المختار لا توجد له طلبات في الفصل.")
        capacity = new_section["capacity"]
        if not isinstance(capacity, int) or not 1 <= capacity <= 50:
            raise ValueError("سعة الشعبة الجديدة يجب أن تكون بين 1 و50.")
        meetings = tuple(_slot(item) for item in new_section["meetings"])
        if not meetings:
            raise ValueError("يجب تحديد موعد للشعبة الجديدة.")
        options.append(SectionOption(-1, course_id, "شعبة جديدة", capacity, meetings, True))
    return options


def _input(term, seat_increases, new_section, meeting_changes):
    requests = list(
        CourseRequest.objects.filter(term=term, enrollment__isnull=True)
        .select_related("student", "course")
        .prefetch_related("student__completed_courses", "course__prerequisites")
    )
    sections = _sections(term, seat_increases, new_section, meeting_changes)
    enrollments = list(
        Enrollment.objects.filter(request__term=term)
        .select_related("request__student", "request__course", "section")
        .prefetch_related("section__meeting_times")
    )
    return requests, sections, enrollments


def _eligible(request) -> bool:
    completed = {course.pk for course in request.student.completed_courses.all()}
    needed = {course.pk for course in request.course.prerequisites.all()}
    return needed <= completed


def solve_term(
    term, time_limit_seconds: int = 10, seat_increases=None,
    protected_request_ids=None, new_section=None, meeting_changes=None,
) -> SolverResult:
    """Optimize required courses, graduation, student coverage, then total seats."""
    if time_limit_seconds <= 0:
        raise ValueError("يجب أن تكون مهلة الحل أكبر من صفر.")
    seat_increases = seat_increases or {}
    meeting_changes = meeting_changes or {}
    protected_request_ids = set(protected_request_ids or ())
    requests, sections, enrollments = _input(term, seat_increases, new_section, meeting_changes)
    if protected_request_ids - {request.pk for request in requests}:
        raise ValueError("طلبات الحماية لا تتبع الفصل أو هي مسجلة مسبقًا.")

    section_by_id = {section.id: section for section in sections}
    sections_by_course = defaultdict(list)
    for section in sections:
        sections_by_course[section.course_id].append(section)

    occupied = Counter(enrollment.section_id for enrollment in enrollments)
    current_by_student = defaultdict(list)
    current_credits = Counter()
    covered_students = set()
    for enrollment in enrollments:
        student_id = enrollment.request.student_id
        current_by_student[student_id].append(section_by_id[enrollment.section_id])
        current_credits[student_id] += enrollment.request.course.credit_hours
        covered_students.add(student_id)
    if any(occupied[item.id] > item.capacity for item in sections if not item.virtual):
        raise ValueError("توجد شعبة يتجاوز تسجيلها الفعلي سعتها.")
    for student_sections in current_by_student.values():
        if any(
            sections_conflict(first, second)
            for index, first in enumerate(student_sections)
            for second in student_sections[index + 1:]
        ):
            raise ValueError("موعد السيناريو يسبب تعارضًا في تسجيلات فعلية.")

    model = cp_model.CpModel()
    variables = {}
    by_request = defaultdict(list)
    by_student = defaultdict(list)
    by_section = defaultdict(list)
    for request in requests:
        if not _eligible(request):
            if request.pk in protected_request_ids:
                raise ValueError("طلب محمي لا يستوفي المتطلبات السابقة.")
            continue
        for section in sections_by_course[request.course_id]:
            variable = model.NewBoolVar(f"r{request.pk}_s{section.id}")
            if any(sections_conflict(section, busy) for busy in current_by_student[request.student_id]):
                model.Add(variable == 0)
            variables[(request.pk, section.id)] = variable
            by_request[request.pk].append(variable)
            by_student[request.student_id].append((request, section, variable))
            by_section[section.id].append(variable)

    for request in requests:
        choices = by_request[request.pk]
        if choices:
            model.Add(sum(choices) <= 1)
            if request.pk in protected_request_ids:
                model.Add(sum(choices) == 1)
        elif request.pk in protected_request_ids:
            raise ValueError("لا توجد شعبة لطلب مطلوب الحفاظ عليه.")

    for section in sections:
        if by_section[section.id]:
            model.Add(sum(by_section[section.id]) <= max(0, section.capacity - occupied[section.id]))

    coverage_variables = []
    for student_id, choices in by_student.items():
        for index, (first_request, first_section, first_var) in enumerate(choices):
            for second_request, second_section, second_var in choices[index + 1:]:
                if first_request.pk != second_request.pk and sections_conflict(first_section, second_section):
                    model.Add(first_var + second_var <= 1)
        student = choices[0][0].student
        remaining_hours = max(0, student.max_credit_hours - current_credits[student_id])
        model.Add(sum(request.course.credit_hours * var for request, _, var in choices) <= remaining_hours)
        if student_id not in covered_students:
            covered = model.NewBoolVar(f"covered_{student_id}")
            model.AddMaxEquality(covered, [var for _, _, var in choices])
            coverage_variables.append(covered)

    n = max(1, len(requests))
    required_weight = (n + 1) ** 3
    graduating_weight = (n + 1) ** 2
    coverage_weight = n + 1
    required_terms = []
    graduating_terms = []
    total_terms = []
    for request in requests:
        for variable in by_request[request.pk]:
            total_terms.append(variable)
            if request.required_for_graduation:
                required_terms.append(variable)
            if request.student.expected_to_graduate:
                graduating_terms.append(variable)
    model.Maximize(
        required_weight * sum(required_terms)
        + graduating_weight * sum(graduating_terms)
        + coverage_weight * sum(coverage_variables)
        + sum(total_terms)
    )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_seconds
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 42
    status_code = solver.Solve(model)
    status = solver.StatusName(status_code)
    if status_code not in {cp_model.OPTIMAL, cp_model.FEASIBLE}:
        return SolverResult(status, [], [request.pk for request in requests], 0, list(covered_students), 0)

    assignments = [
        Assignment(request_id, section_id)
        for (request_id, section_id), variable in variables.items()
        if solver.Value(variable)
    ]
    assigned_ids = {item.request_id for item in assignments}
    student_by_request = {request.pk: request.student_id for request in requests}
    covered_students.update(student_by_request[item.request_id] for item in assignments)
    return SolverResult(
        status, assignments,
        [request.pk for request in requests if request.pk not in assigned_ids],
        solver.ObjectiveValue(), sorted(covered_students), solver.BestObjectiveBound(),
    )


def diagnose_unassigned(term, result: SolverResult, seat_increases=None, new_section=None, meeting_changes=None):
    """Give a possible explanation against the final proposed allocation."""
    if not result.unassigned_request_ids:
        return {}
    seat_increases = seat_increases or {}
    requests, sections, enrollments = _input(term, seat_increases, new_section, meeting_changes or {})
    unassigned = set(result.unassigned_request_ids)
    section_by_id = {section.id: section for section in sections}
    by_course = defaultdict(list)
    for section in sections:
        by_course[section.course_id].append(section)
    occupied = Counter(enrollment.section_id for enrollment in enrollments)
    busy = defaultdict(list)
    credits = Counter()
    for enrollment in enrollments:
        student_id = enrollment.request.student_id
        busy[student_id].append(section_by_id[enrollment.section_id])
        credits[student_id] += enrollment.request.course.credit_hours
    by_request = {request.pk: request for request in requests}
    for assignment in result.assignments:
        request = by_request[assignment.request_id]
        occupied[assignment.section_id] += 1
        busy[request.student_id].append(section_by_id[assignment.section_id])
        credits[request.student_id] += request.course.credit_hours

    reasons = {}
    for request in requests:
        if request.pk not in unassigned:
            continue
        if not _eligible(request):
            reason = "المتطلبات السابقة غير مكتملة"
        elif credits[request.student_id] + request.course.credit_hours > request.student.max_credit_hours:
            reason = "تجاوز حد الساعات"
        else:
            options = by_course[request.course_id]
            if not options:
                reason = "لا توجد شعبة لهذا المقرر"
            else:
                available = [section for section in options if occupied[section.id] < section.capacity]
                if not available:
                    reason = "الشعب ممتلئة بعد التوزيع"
                elif all(any(sections_conflict(section, item) for item in busy[request.student_id]) for section in available):
                    reason = "تعارض المواعيد مع التوزيع المقترح"
                else:
                    reason = "ترتيب الأولويات والتوزيع بين الطلاب"
        reasons[str(request.pk)] = reason
    return reasons


def recommend_seat_increases(term, baseline: SolverResult, time_limit_seconds=1):
    """Try one extra seat in each full section and return the three strongest options."""
    if baseline.status not in {"OPTIMAL", "FEASIBLE"}:
        return []
    sections = list(Section.objects.filter(term=term).select_related("course"))
    occupied = Counter(Enrollment.objects.filter(request__term=term).values_list("section_id", flat=True))
    occupied.update(item.section_id for item in baseline.assignments if item.section_id > 0)
    baseline_ids = {item.request_id for item in baseline.assignments}
    unmet = set(baseline.unassigned_request_ids)
    unmet_requests = list(
        CourseRequest.objects.filter(pk__in=unmet).select_related("student", "course")
    )
    course_unmet = Counter(item.course_id for item in unmet_requests)
    request_by_id = {item.pk: item for item in unmet_requests}
    recommendations = []
    for section in sections:
        if occupied[section.pk] < section.capacity or not course_unmet[section.course_id]:
            continue
        result = solve_term(
            term, time_limit_seconds=time_limit_seconds,
            seat_increases={section.pk: 1}, protected_request_ids=baseline_ids,
        )
        if result.status not in {"OPTIMAL", "FEASIBLE"}:
            continue
        gained = {item.request_id for item in result.assignments} - baseline_ids
        if not gained:
            continue
        recommendations.append({
            "section_id": section.pk,
            "course": section.course.title,
            "code": section.code,
            "gain": len(gained),
            "graduating_gain": sum(request_by_id[item].student.expected_to_graduate for item in gained),
            "required_gain": sum(request_by_id[item].required_for_graduation for item in gained),
            "status": result.status,
            "reason": f"{course_unmet[section.course_id]} طلبًا لم يُوزّع لهذا المقرر بعد الحساب الأساسي.",
        })
    return sorted(
        recommendations,
        key=lambda item: (-item["gain"], -item["graduating_gain"], -item["required_gain"], item["course"], item["code"]),
    )[:3]
