"""Persist a self-contained optimization result for audit and public example views."""

import hashlib
import json

from django.db import transaction

from academics.models import Course, CourseRequest, Enrollment, MeetingTime, Section, Student

from optimizer.models import OptimizationRun, ProposedEnrollment
from optimizer.services.solver import POLICY_VERSION, diagnose_unassigned


def fingerprint_term(term):
    requests = list(CourseRequest.objects.filter(term=term).order_by("pk").values_list(
        "pk", "student_id", "student__full_name", "student__student_number",
        "student__expected_to_graduate", "student__max_credit_hours", "course_id", "course__code", "course__title",
        "course__credit_hours", "required_for_graduation",
    ))
    course_ids = {item[6] for item in requests}
    student_ids = {item[1] for item in requests}
    sections = list(Section.objects.filter(term=term).order_by("pk").values_list(
        "pk", "course_id", "code", "capacity",
    ))
    meetings = list(MeetingTime.objects.filter(section__term=term).order_by("pk").values_list(
        "section_id", "weekday", "start_time", "end_time",
    ))
    prerequisites = list(Course.prerequisites.through.objects.filter(from_course_id__in=course_ids)
                         .order_by("from_course_id", "to_course_id")
                         .values_list("from_course_id", "to_course_id"))
    completed = list(Student.completed_courses.through.objects.filter(student_id__in=student_ids)
                     .order_by("student_id", "course_id")
                     .values_list("student_id", "course_id"))
    enrollments = list(Enrollment.objects.filter(request__term=term).order_by("pk").values_list(
        "request_id", "section_id",
    ))
    payload = json.dumps(
        [term.name, requests, sections, meetings, prerequisites, completed, enrollments],
        ensure_ascii=False, sort_keys=True, default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _row(request, section_id, section_by_id, reason=""):
    section = section_by_id.get(section_id)
    return {
        "request_id": request.pk,
        "student_name": request.student.full_name,
        "student_number": request.student.student_number,
        "course_code": request.course.code,
        "course_title": request.course.title,
        "section_code": section.code if section else "شعبة جديدة",
        "graduating": request.student.expected_to_graduate,
        "required": request.required_for_graduation,
        "reason": reason,
    }


def save_result(
    term, result, baseline_result=None, scenario_type=OptimizationRun.Scenario.BASELINE,
    scenario_section=None, extra_seats=0, scenario_settings=None, recommendations=None,
    new_section=None, meeting_changes=None,
):
    baseline_result = baseline_result or result
    scenario_settings = {**(scenario_settings or {}), "term_name": term.name}
    recommendations = recommendations or []
    seat_increases = {scenario_section.pk: extra_seats} if scenario_type == OptimizationRun.Scenario.SEATS else {}
    reasons = diagnose_unassigned(
        term, result, seat_increases=seat_increases,
        new_section=new_section, meeting_changes=meeting_changes,
    )
    requests = {
        item.pk: item for item in CourseRequest.objects.filter(term=term)
        .select_related("student", "course")
    }
    sections = {
        item.pk: item for item in Section.objects.filter(term=term).select_related("course")
    }
    proposal_rows = [
        _row(requests[item.request_id], item.section_id, sections)
        for item in result.assignments
    ]
    unassigned_rows = [
        _row(requests[request_id], None, sections, reasons.get(str(request_id), "غير محدد"))
        for request_id in result.unassigned_request_ids
    ]
    before_ids = set(Enrollment.objects.filter(request__term=term).values_list("request_id", flat=True))
    graduating_ids = {
        item.pk for item in requests.values() if item.student.expected_to_graduate
    }
    baseline_ids = {item.request_id for item in baseline_result.assignments}
    result_ids = {item.request_id for item in result.assignments}

    with transaction.atomic():
        run = OptimizationRun.objects.create(
            term=term,
            status=OptimizationRun.Status.COMPLETED,
            scenario_type=scenario_type,
            scenario_settings=scenario_settings,
            scenario_section=scenario_section,
            extra_seats=extra_seats,
            total_requests=len(requests),
            before_assigned=len(before_ids),
            baseline_after_assigned=len(before_ids | baseline_ids),
            after_assigned=len(before_ids | result_ids),
            baseline_graduating_assigned=len((before_ids | baseline_ids) & graduating_ids),
            after_graduating_assigned=len((before_ids | result_ids) & graduating_ids),
            baseline_covered_students=len(baseline_result.covered_student_ids),
            after_covered_students=len(result.covered_student_ids),
            newly_assigned_count=len(result_ids - baseline_ids),
            baseline_solver_status=baseline_result.status,
            solver_status=result.status,
            recommendations=recommendations,
            proposal_snapshot=proposal_rows,
            unassigned_snapshot=unassigned_rows,
            unassigned_request_ids=result.unassigned_request_ids,
            unassigned_reasons=reasons,
            data_fingerprint=fingerprint_term(term),
            solver_version=POLICY_VERSION,
        )
        ProposedEnrollment.objects.bulk_create([
            ProposedEnrollment(
                run=run,
                request_id=item.request_id,
                section_id=item.section_id if item.section_id > 0 else None,
                virtual_section_label="شعبة جديدة" if item.section_id < 0 else "",
            )
            for item in result.assignments
        ])
    return run
