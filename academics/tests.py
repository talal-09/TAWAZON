from datetime import time
from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from .models import AcademicTerm, Course, CourseRequest, Enrollment, MeetingTime, Section, Student
from optimizer.models import OptimizationRun


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


class CourseManagementTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='talal1', password='test-password')
        self.course = Course.objects.create(code='CS101', title='مقدمة الحاسب')

    def grant(self, *codenames):
        self.user.is_staff = True
        self.user.save(update_fields=['is_staff'])
        self.user.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='academics', codename__in=codenames,
        ))
        self.client.force_login(self.user)

    def test_regular_user_cannot_manage_courses(self):
        self.client.force_login(self.user)
        for name, args in (
            ('academics:course_create', []),
            ('academics:course_edit', [self.course.pk]),
            ('academics:course_delete', [self.course.pk]),
        ):
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 403)
        response = self.client.get(reverse('academics:home'))
        self.assertNotContains(response, 'إدارة المقررات')

    def test_staff_without_permission_cannot_manage_courses(self):
        self.grant()
        self.assertEqual(self.client.get(reverse('academics:course_create')).status_code, 403)

    def test_create_edit_and_delete_unlinked_course(self):
        self.grant('add_course', 'change_course', 'delete_course')
        response = self.client.get(reverse('academics:home'))
        self.assertContains(response, 'إدارة المقررات')
        self.assertContains(response, 'إضافة مقرر')

        response = self.client.post(reverse('academics:course_create'), {
            'code': ' ai301 ', 'title': 'الذكاء الاصطناعي', 'credit_hours': 3,
        })
        self.assertEqual(response.status_code, 302)
        added = Course.objects.get(code='AI301')
        self.assertContains(self.client.get(reverse('academics:home')), 'الذكاء الاصطناعي')

        response = self.client.post(reverse('academics:course_edit', args=[added.pk]), {
            'code': 'AI301', 'title': 'مبادئ الذكاء الاصطناعي', 'credit_hours': 4,
        })
        self.assertEqual(response.status_code, 302)
        added.refresh_from_db()
        self.assertEqual(added.credit_hours, 4)

        response = self.client.post(reverse('academics:course_delete', args=[added.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Course.objects.filter(pk=added.pk).exists())

    def test_invalid_course_and_duplicate_code_are_rejected(self):
        self.grant('add_course')
        for code, hours in (('cs101', 3), ('AI301', 0)):
            response = self.client.post(reverse('academics:course_create'), {
                'code': code, 'title': 'مادة', 'credit_hours': hours,
            })
            self.assertEqual(response.status_code, 200)
        self.assertEqual(Course.objects.count(), 1)

    def test_linked_course_cannot_be_deleted(self):
        self.grant('delete_course')
        term = AcademicTerm.objects.create(name='فصل الاختبار')
        Section.objects.create(term=term, course=self.course, code='A', capacity=10)
        student = Student.objects.create(student_number='439000001', full_name='طالب')
        CourseRequest.objects.create(student=student, term=term, course=self.course)
        url = reverse('academics:course_delete', args=[self.course.pk])
        self.assertContains(self.client.get(url), 'لا يمكن حذف هذا المقرر')
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertTrue(Course.objects.filter(pk=self.course.pk).exists())
        self.assertEqual(CourseRequest.objects.filter(course=self.course).count(), 1)

    def test_editing_linked_course_marks_saved_result_as_historical(self):
        call_command('prepare_showcase', stdout=StringIO())
        run = OptimizationRun.objects.filter(scenario_type='seats').first()
        self.grant('change_course')
        course = Course.objects.get(code='AI401')
        response = self.client.post(reverse('academics:course_edit', args=[course.pk]), {
            'code': 'AI401', 'title': 'مقرر الذكاء المتقدم', 'credit_hours': 3,
        })
        self.assertEqual(response.status_code, 302)
        self.assertContains(self.client.get(reverse('academics:home')), 'مقرر الذكاء المتقدم')
        result_page = self.client.get(reverse('optimizer:home'), {'run': run.pk})
        self.assertContains(result_page, 'تغيّرت بيانات هذا الفصل')

    def test_adding_and_deleting_unlinked_course_does_not_change_request_totals(self):
        call_command('prepare_showcase', stdout=StringIO())
        self.grant('add_course', 'delete_course')
        term = AcademicTerm.objects.get(name='فصل توازن الموسع 2026')
        before = self.client.get(reverse('academics:home'))
        self.assertEqual((before.context['requests_count'],
                          before.context['graduating_students_count']), (204, 13))

        self.assertEqual(self.client.post(reverse('academics:course_create'), {
            'code': 'EXTRA101', 'title': 'مقرر جديد', 'credit_hours': 3,
        }).status_code, 302)
        added = Course.objects.get(code='EXTRA101')
        self.assertContains(self.client.get(reverse('academics:home')), 'مقرر جديد')
        self.assertFalse(CourseRequest.objects.filter(term=term, course=added).exists())

        self.assertEqual(self.client.post(reverse('academics:course_delete', args=[added.pk])).status_code, 302)
        self.assertFalse(Course.objects.filter(pk=added.pk).exists())
        after = self.client.get(reverse('academics:home'))
        self.assertEqual((after.context['requests_count'],
                          after.context['graduating_students_count']), (204, 13))

    def test_post_requires_csrf(self):
        self.grant('add_course')
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        response = client.post(reverse('academics:course_create'), {
            'code': 'AI301', 'title': 'الذكاء الاصطناعي', 'credit_hours': 3,
        })
        self.assertEqual(response.status_code, 403)

    def test_grant_command_gives_limited_permissions(self):
        call_command('grant_tawazon_manager', 'talal1', stdout=StringIO())
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_staff)
        self.assertFalse(self.user.is_superuser)
        self.assertTrue(self.user.has_perm('academics.add_course'))
        self.assertTrue(self.user.has_perm('optimizer.add_optimizationrun'))
        self.assertFalse(self.user.has_perm('auth.change_user'))
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('academics:course_create')).status_code, 200)
