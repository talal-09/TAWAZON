from datetime import time

from django.core.exceptions import ValidationError
from django.test import TestCase

from academics.models import (
    AcademicTerm,
    Course,
    CourseRequest,
    Enrollment,
    MeetingTime,
    Section,
    Student,
)

from .models import OptimizationRun, ProposedEnrollment
from .services.solver import solve_term


class ProposedEnrollmentTests(TestCase):
    def test_proposal_must_match_requested_course(self):
        term = AcademicTerm.objects.create(name="الفصل الأول 2026")
        student = Student.objects.create(
            student_number="1001",
            full_name="طالب تجريبي",
        )
        requested_course = Course.objects.create(
            code="CS101",
            title="مقدمة الحاسب",
        )
        other_course = Course.objects.create(
            code="CS102",
            title="برمجة",
        )
        request = CourseRequest.objects.create(
            student=student,
            course=requested_course,
            term=term,
        )
        section = Section.objects.create(
            term=term,
            course=other_course,
            code="A",
            capacity=30,
        )
        run = OptimizationRun.objects.create(term=term)

        proposal = ProposedEnrollment(
            run=run,
            request=request,
            section=section,
        )

        with self.assertRaises(ValidationError):
            proposal.full_clean()


class SolverTests(TestCase):
    def setUp(self):
        self.term = AcademicTerm.objects.create(
            name="الفصل الأول 2026",
        )

        self.course = Course.objects.create(
            code="CS401",
            title="الذكاء الاصطناعي",
        )

        self.section = Section.objects.create(
            term=self.term,
            course=self.course,
            code="A",
            capacity=1,
        )

        MeetingTime.objects.create(
            section=self.section,
            weekday=MeetingTime.Weekday.SUNDAY,
            start_time=time(9, 0),
            end_time=time(10, 0),
        )

    def test_graduating_student_receives_priority(self):
        graduating_student = Student.objects.create(
            student_number="1001",
            full_name="طالب متوقع تخرجه",
            expected_to_graduate=True,
        )
        regular_student = Student.objects.create(
            student_number="1002",
            full_name="طالب عادي",
        )

        graduating_request = CourseRequest.objects.create(
            student=graduating_student,
            course=self.course,
            term=self.term,
            required_for_graduation=True,
        )
        regular_request = CourseRequest.objects.create(
            student=regular_student,
            course=self.course,
            term=self.term,
        )

        result = solve_term(self.term)

        assigned_request_ids = {
            assignment.request_id
            for assignment in result.assignments
        }

        self.assertIn(result.status, {"OPTIMAL", "FEASIBLE"})
        self.assertIn(graduating_request.id, assigned_request_ids)
        self.assertNotIn(regular_request.id, assigned_request_ids)

    def test_student_cannot_receive_conflicting_sections(self):
        student = Student.objects.create(
            student_number="2001",
            full_name="طالب لديه تعارض",
        )

        second_course = Course.objects.create(
            code="CS402",
            title="تعلم الآلة",
        )
        second_section = Section.objects.create(
            term=self.term,
            course=second_course,
            code="A",
            capacity=30,
        )

        MeetingTime.objects.create(
            section=second_section,
            weekday=MeetingTime.Weekday.SUNDAY,
            start_time=time(9, 30),
            end_time=time(10, 30),
        )

        preferred_request = CourseRequest.objects.create(
            student=student,
            course=self.course,
            term=self.term,
            required_for_graduation=True,
        )
        CourseRequest.objects.create(
            student=student,
            course=second_course,
            term=self.term,
        )

        result = solve_term(self.term)

        student_assignments = [
            assignment
            for assignment in result.assignments
            if assignment.request_id == preferred_request.id
        ]

        self.assertIn(result.status, {"OPTIMAL", "FEASIBLE"})
        self.assertEqual(len(result.assignments), 1)
        self.assertEqual(len(student_assignments), 1)

    def test_request_without_section_is_unassigned(self):
        student = Student.objects.create(
            student_number="3001",
            full_name="طالب دون شعبة",
        )
        unavailable_course = Course.objects.create(
            code="CS499",
            title="موضوعات مختارة",
        )
        request = CourseRequest.objects.create(
            student=student,
            course=unavailable_course,
            term=self.term,
        )

        result = solve_term(self.term)

        self.assertIn(result.status, {"OPTIMAL", "FEASIBLE"})
        self.assertIn(request.id, result.unassigned_request_ids)

    def test_existing_enrollment_uses_section_capacity(self):
        enrolled_student = Student.objects.create(
            student_number="4001", full_name="طالب مسجل"
        )
        waiting_student = Student.objects.create(
            student_number="4002", full_name="طالب منتظر"
        )
        enrolled_request = CourseRequest.objects.create(
            student=enrolled_student, course=self.course, term=self.term
        )
        waiting_request = CourseRequest.objects.create(
            student=waiting_student, course=self.course, term=self.term
        )
        Enrollment.objects.create(request=enrolled_request, section=self.section)

        result = solve_term(self.term)

        self.assertEqual(result.assignments, [])
        self.assertEqual(result.unassigned_request_ids, [waiting_request.id])

    def test_existing_enrollment_blocks_time_conflict(self):
        student = Student.objects.create(
            student_number="5001", full_name="طالب مسجل"
        )
        enrolled_request = CourseRequest.objects.create(
            student=student, course=self.course, term=self.term
        )
        Enrollment.objects.create(request=enrolled_request, section=self.section)
        other_course = Course.objects.create(
            code="CS403", title="قواعد البيانات"
        )
        other_section = Section.objects.create(
            term=self.term, course=other_course, code="A", capacity=1
        )
        MeetingTime.objects.create(
            section=other_section,
            weekday=MeetingTime.Weekday.SUNDAY,
            start_time=time(9, 30),
            end_time=time(10, 30),
        )
        conflicting_request = CourseRequest.objects.create(
            student=student, course=other_course, term=self.term
        )

        result = solve_term(self.term)

        self.assertEqual(result.assignments, [])
        self.assertEqual(result.unassigned_request_ids, [conflicting_request.id])

    def test_section_without_meeting_time_is_rejected(self):
        unscheduled_course = Course.objects.create(
            code="CS404", title="الشبكات"
        )
        Section.objects.create(
            term=self.term, course=unscheduled_course, code="A", capacity=1
        )

        with self.assertRaisesMessage(ValueError, "موعد"):
            solve_term(self.term)
