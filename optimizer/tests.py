from datetime import time
from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from academics.models import (
    AcademicTerm,
    Course,
    CourseRequest,
    Enrollment,
    MeetingTime,
    Section,
    Student,
)
from academics.management.commands.seed_demo import DEMO_TERM_NAME, LARGE_DEMO_TERM_NAME

from .models import OptimizationRun, ProposedEnrollment
from .services.solver import diagnose_unassigned, solve_term


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
        self.assertEqual(
            diagnose_unassigned(self.term, result)[str(request.id)],
            "لا توجد شعبة لهذا المقرر",
        )

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
        self.assertEqual(
            diagnose_unassigned(self.term, result)[str(waiting_request.id)],
            "جميع الشعب ممتلئة",
        )

        scenario = solve_term(self.term, seat_increases={self.section.pk: 1})
        self.assertEqual([item.request_id for item in scenario.assignments], [waiting_request.id])
        self.section.refresh_from_db()
        self.assertEqual(self.section.capacity, 1)

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
        self.assertEqual(
            diagnose_unassigned(self.term, result)[str(conflicting_request.id)],
            "جميع الشعب المتاحة تتعارض مع جدول الطالب",
        )

    def test_section_without_meeting_time_is_rejected(self):
        unscheduled_course = Course.objects.create(
            code="CS404", title="الشبكات"
        )
        Section.objects.create(
            term=self.term, course=unscheduled_course, code="A", capacity=1
        )

        with self.assertRaisesMessage(ValueError, "موعد"):
            solve_term(self.term)


class DemoDataTests(TestCase):
    def test_demo_data_is_repeatable_and_shows_improvement(self):
        output = StringIO()
        call_command("seed_demo", stdout=output)
        term = AcademicTerm.objects.get(name=DEMO_TERM_NAME)
        counts = (
            Student.objects.count(),
            Course.objects.count(),
            Section.objects.count(),
            MeetingTime.objects.count(),
            CourseRequest.objects.count(),
            Enrollment.objects.count(),
        )

        call_command("seed_demo", stdout=output)

        self.assertEqual(counts, (6, 2, 3, 3, 7, 1))
        self.assertEqual(
            counts,
            (
                Student.objects.count(),
                Course.objects.count(),
                Section.objects.count(),
                MeetingTime.objects.count(),
                CourseRequest.objects.count(),
                Enrollment.objects.count(),
            ),
        )

        result = solve_term(term)
        assigned_ids = {assignment.request_id for assignment in result.assignments}
        graduating_request_ids = set(
            CourseRequest.objects.filter(
                term=term, student__expected_to_graduate=True
            ).values_list("id", flat=True)
        )

        self.assertEqual(result.status, "OPTIMAL")
        self.assertEqual(len(result.assignments), 4)
        self.assertEqual(len(result.unassigned_request_ids), 2)
        self.assertTrue(graduating_request_ids <= assigned_ids)

    def test_large_demo_has_100_students_and_is_repeatable(self):
        output = StringIO()
        call_command("seed_demo", large=True, stdout=output)
        term = AcademicTerm.objects.get(name=LARGE_DEMO_TERM_NAME)
        students = Student.objects.exclude(student_number__startswith="DEMO")
        numbers = list(students.values_list("student_number", flat=True))

        self.assertEqual(len(numbers), 100)
        self.assertTrue(all(len(number) == 9 and 439 <= int(number[:3]) <= 446 for number in numbers))
        self.assertEqual(students.filter(student_number__startswith="439").count(), 13)
        self.assertEqual(students.filter(expected_to_graduate=True).count(), 13)
        self.assertEqual(Course.objects.filter(sections__term=term).distinct().count(), 5)
        self.assertEqual(Section.objects.filter(term=term).count(), 10)
        self.assertEqual(CourseRequest.objects.filter(term=term).count(), 200)

        call_command("seed_demo", large=True, stdout=output)
        self.assertEqual(CourseRequest.objects.filter(term=term).count(), 200)
        self.assertEqual(Student.objects.count(), 106)

        result = solve_term(term)
        assigned_ids = {assignment.request_id for assignment in result.assignments}
        graduate_ids = set(CourseRequest.objects.filter(
            term=term, student__expected_to_graduate=True,
        ).values_list("pk", flat=True))
        self.assertIn(result.status, {"OPTIMAL", "FEASIBLE"})
        self.assertTrue(graduate_ids <= assigned_ids)


class OptimizationPageTests(TestCase):
    def setUp(self):
        call_command('seed_demo', stdout=StringIO())
        self.term = AcademicTerm.objects.get(name=DEMO_TERM_NAME)
        self.url = reverse('optimizer:home')
        self.admin = get_user_model().objects.create(
            username='optimization_admin', is_staff=True, is_superuser=True
        )

    def test_run_saves_and_displays_snapshot(self):
        self.client.force_login(self.admin)

        response = self.client.post(self.url, {'term': self.term.pk})

        self.assertEqual(response.status_code, 302)
        run = OptimizationRun.objects.get()
        self.assertEqual(run.status, OptimizationRun.Status.COMPLETED)
        self.assertEqual((run.before_assigned, run.after_assigned, run.total_requests), (1, 5, 7))
        self.assertEqual(len(run.unassigned_request_ids), 2)
        self.assertEqual(set(run.unassigned_reasons), {
            str(request_id) for request_id in run.unassigned_request_ids
        })
        self.assertTrue(all(run.unassigned_reasons.values()))
        self.assertEqual(run.proposed_enrollments.count(), 4)

        page = self.client.get(response['Location'])
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context['run'], run)
        self.assertContains(page, 'الطلبات المسندة بعد المقترح')
        self.assertContains(page, 'طلبات لم تجد مقعدًا')
        self.assertContains(page, 'سبب عدم التوزيع')

    def test_staff_needs_permission_to_run(self):
        staff = get_user_model().objects.create(username='viewer', is_staff=True)
        permission = Permission.objects.get(
            codename='view_optimizationrun', content_type__app_label='optimizer'
        )
        staff.user_permissions.add(permission)
        self.client.force_login(staff)

        page = self.client.get(self.url)
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, 'قارن السيناريو')
        self.assertEqual(self.client.post(self.url, {'term': self.term.pk}).status_code, 403)
        section = Section.objects.filter(term=self.term).first()
        self.assertEqual(self.client.post(self.url, {
            'action': 'scenario', 'term': self.term.pk,
            'section': section.pk, 'extra_seats': 2,
        }).status_code, 403)
        self.assertFalse(OptimizationRun.objects.exists())

    def test_page_requires_staff_and_view_permission(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)
        non_staff = get_user_model().objects.create(username='student')
        self.client.force_login(non_staff)
        self.assertEqual(self.client.get(self.url).status_code, 302)
        staff = get_user_model().objects.create(username='staff', is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_scenario_compares_results_without_changing_capacity(self):
        self.client.force_login(self.admin)
        section = Section.objects.get(term=self.term, course__code='DEMO-CS401', code='A')
        original_capacity = section.capacity

        response = self.client.post(self.url, {
            'action': 'scenario', 'term': self.term.pk,
            'section': section.pk, 'extra_seats': 3,
        })

        self.assertEqual(response.status_code, 302)
        run = OptimizationRun.objects.get()
        self.assertEqual(run.scenario_section, section)
        self.assertEqual(run.extra_seats, 3)
        self.assertGreater(run.after_assigned, run.baseline_after_assigned)
        self.assertEqual(run.newly_assigned_count, run.after_assigned - run.baseline_after_assigned)
        self.assertGreaterEqual(run.after_graduating_assigned, run.baseline_graduating_assigned)
        self.assertEqual(Enrollment.objects.filter(request__term=self.term).count(), 1)
        section.refresh_from_db()
        self.assertEqual(section.capacity, original_capacity)
        page = self.client.get(response['Location'])
        self.assertContains(page, 'المسند دون الزيادة')
        self.assertContains(page, 'طلبات استفادت')

    def test_scenario_rejects_section_from_another_term_and_excess_seats(self):
        self.client.force_login(self.admin)
        other_term = AcademicTerm.objects.create(name='فصل آخر')
        other_section = Section.objects.create(
            term=other_term, course=Course.objects.first(), code='X', capacity=10,
        )
        for section_id, extra_seats in ((other_section.pk, 2), (Section.objects.first().pk, 51)):
            response = self.client.post(self.url, {
                'action': 'scenario', 'term': self.term.pk,
                'section': section_id, 'extra_seats': extra_seats,
            })
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context['scenario_form'].errors)
        self.assertFalse(OptimizationRun.objects.exists())

    def test_invalid_term_does_not_create_run(self):
        self.client.force_login(self.admin)

        response = self.client.post(self.url, {'term': 'invalid'})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(OptimizationRun.objects.exists())
        self.assertTrue(response.context['form'].errors)

    def test_unknown_action_does_not_run_solver(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.url, {'action': 'unknown', 'term': self.term.pk})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(OptimizationRun.objects.exists())

    def test_form_requires_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)

        response = client.post(self.url, {'term': self.term.pk})

        self.assertEqual(response.status_code, 403)
        self.assertFalse(OptimizationRun.objects.exists())

        section = Section.objects.filter(term=self.term).first()
        response = client.post(self.url, {
            'action': 'scenario', 'term': self.term.pk,
            'section': section.pk, 'extra_seats': 2,
        })
        self.assertEqual(response.status_code, 403)
        self.assertFalse(OptimizationRun.objects.exists())

    def test_bad_run_id_returns_not_found(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.url, {'run': 'invalid'}).status_code, 404)
