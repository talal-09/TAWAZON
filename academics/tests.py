from datetime import time

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from .models import AcademicTerm, Course, CourseRequest, Enrollment, MeetingTime, Section, Student


class AcademicModelTests(TestCase):
    def setUp(self):
        self.term = AcademicTerm.objects.create(name='الفصل الأول 2026')
        self.student = Student.objects.create(student_number='1001', full_name='طالب تجريبي')
        self.course = Course.objects.create(code='CS101', title='مقدمة الحاسب')
        self.other_course = Course.objects.create(code='CS102', title='برمجة')
        self.section = Section.objects.create(term=self.term, course=self.course, code='A', capacity=30)
        self.request = CourseRequest.objects.create(student=self.student, course=self.course, term=self.term)

    def test_meeting_time_must_end_after_start(self):
        meeting = MeetingTime(section=self.section, weekday=MeetingTime.Weekday.SUNDAY,
                              start_time=time(10), end_time=time(9))
        with self.assertRaises(ValidationError):
            meeting.full_clean()

    def test_enrollment_must_match_requested_course(self):
        other_section = Section.objects.create(term=self.term, course=self.other_course, code='A', capacity=30)
        enrollment = Enrollment(request=self.request, section=other_section)
        with self.assertRaises(ValidationError):
            enrollment.full_clean()


class AdminAccessTests(TestCase):
    def test_admin_requires_staff_access(self):
        section_url = reverse('admin:academics_section_changelist')
        proposal_url = reverse('admin:optimizer_proposedenrollment_changelist')

        self.assertEqual(self.client.get(section_url).status_code, 302)

        staff = get_user_model().objects.create(username='admin', is_staff=True, is_superuser=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(section_url).status_code, 200)
        self.assertEqual(self.client.get(proposal_url).status_code, 200)
