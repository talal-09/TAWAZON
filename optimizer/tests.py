from django.core.exceptions import ValidationError
from django.test import TestCase

from academics.models import AcademicTerm, Course, CourseRequest, Section, Student

from .models import OptimizationRun, ProposedEnrollment


class ProposedEnrollmentTests(TestCase):
    def test_proposal_must_match_requested_course(self):
        term = AcademicTerm.objects.create(name='الفصل الأول 2026')
        student = Student.objects.create(student_number='1001', full_name='طالب تجريبي')
        requested_course = Course.objects.create(code='CS101', title='مقدمة الحاسب')
        other_course = Course.objects.create(code='CS102', title='برمجة')
        request = CourseRequest.objects.create(student=student, course=requested_course, term=term)
        section = Section.objects.create(term=term, course=other_course, code='A', capacity=30)
        run = OptimizationRun.objects.create(term=term)

        with self.assertRaises(ValidationError):
            ProposedEnrollment(run=run, request=request, section=section).full_clean()
