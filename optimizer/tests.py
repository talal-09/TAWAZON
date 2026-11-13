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
from academics.management.commands.seed_example import (
    EXAMPLE_TERM_NAME, LARGE_EXAMPLE_TERM_NAME, UNSCHEDULED_COURSE,
)

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
            "الشعب ممتلئة بعد التوزيع",
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
            "تعارض المواعيد مع التوزيع المقترح",
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


class ExampleDataTests(TestCase):
    def test_example_data_is_repeatable_and_shows_improvement(self):
        output = StringIO()
        call_command("seed_example", stdout=output)
        term = AcademicTerm.objects.get(name=EXAMPLE_TERM_NAME)
        counts = (
            Student.objects.count(),
            Course.objects.count(),
            Section.objects.count(),
            MeetingTime.objects.count(),
            CourseRequest.objects.count(),
            Enrollment.objects.count(),
        )

        call_command("seed_example", stdout=output)

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

    def test_large_example_has_100_students_and_is_repeatable(self):
        output = StringIO()
        call_command("seed_example", large=True, stdout=output)
        term = AcademicTerm.objects.get(name=LARGE_EXAMPLE_TERM_NAME)
        students = Student.objects.exclude(student_number__startswith="EX")
        numbers = list(students.values_list("student_number", flat=True))

        self.assertEqual(len(numbers), 100)
        self.assertTrue(all(len(number) == 9 and 439 <= int(number[:3]) <= 446 for number in numbers))
        self.assertEqual(students.filter(student_number__startswith="439").count(), 13)
        self.assertEqual(students.filter(expected_to_graduate=True).count(), 13)
        self.assertEqual(Course.objects.filter(sections__term=term).distinct().count(), 5)
        self.assertEqual(Section.objects.filter(term=term).count(), 10)
        self.assertEqual(CourseRequest.objects.filter(term=term).count(), 204)
        missing_section = Course.objects.get(code=UNSCHEDULED_COURSE[0])
        self.assertFalse(Section.objects.filter(term=term, course=missing_section).exists())
        self.assertEqual(CourseRequest.objects.filter(
            term=term, course=missing_section,
            required_for_graduation=True,
            student__expected_to_graduate=True,
        ).count(), 4)

        call_command("seed_example", large=True, stdout=output)
        self.assertEqual(CourseRequest.objects.filter(term=term).count(), 204)
        self.assertEqual(Student.objects.count(), 106)

        result = solve_term(term)
        assigned_ids = {assignment.request_id for assignment in result.assignments}
        graduate_ids = set(CourseRequest.objects.filter(
            term=term, student__expected_to_graduate=True,
        ).values_list("pk", flat=True))
        self.assertIn(result.status, {"OPTIMAL", "FEASIBLE"})
        self.assertEqual(len(result.assignments), 140)
        self.assertEqual(len(result.unassigned_request_ids), 64)
        missing_graduate_ids = graduate_ids - assigned_ids
        self.assertEqual(len(missing_graduate_ids), 4)
        reasons = diagnose_unassigned(term, result)
        self.assertTrue(all(
            reasons[str(request_id)] == 'لا توجد شعبة لهذا المقرر'
            for request_id in missing_graduate_ids
        ))

        scenario = solve_term(term, new_section={
            'course_id': missing_section.pk, 'capacity': 4,
            'meetings': [{
                'weekday': MeetingTime.Weekday.THURSDAY,
                'start_time': time(13), 'end_time': time(14),
            }],
        }, protected_request_ids=assigned_ids)
        self.assertIn(scenario.status, {'OPTIMAL', 'FEASIBLE'})
        self.assertEqual(len(scenario.assignments), 144)
        self.assertTrue(missing_graduate_ids <= {
            item.request_id for item in scenario.assignments
        })

    def test_showcase_counts_match_saved_result_and_missing_sections(self):
        call_command('prepare_showcase', stdout=StringIO())
        term = AcademicTerm.objects.get(name=LARGE_EXAMPLE_TERM_NAME)
        run = OptimizationRun.objects.filter(term=term, scenario_type='seats').first()
        requests = CourseRequest.objects.filter(term=term)

        self.assertEqual((requests.values('student_id').distinct().count(),
                          requests.values('course_id').distinct().count(),
                          Section.objects.filter(term=term).count(), requests.count()),
                         (100, 6, 10, 204))
        self.assertEqual((run.baseline_after_assigned, run.after_assigned,
                          len(run.unassigned_request_ids)), (140, 150, 54))
        self.assertEqual((run.baseline_graduating_assigned,
                          run.after_graduating_assigned), (26, 26))
        self.assertEqual(sum(
            row['course_code'] == UNSCHEDULED_COURSE[0]
            and row['graduating']
            and row['reason'] == 'لا توجد شعبة لهذا المقرر'
            for row in run.unassigned_snapshot
        ), 4)
        page = self.client.get(reverse('optimizer:home'), {'run': run.pk})
        self.assertContains(page, 'من أصل 30 طلبًا')


class OptimizationPageTests(TestCase):
    def setUp(self):
        call_command('seed_example', stdout=StringIO())
        self.term = AcademicTerm.objects.get(name=EXAMPLE_TERM_NAME)
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
        self.assertContains(page, 'المقترح بعد التوزيع')
        self.assertContains(page, 'طلبات لم تجد مقعدًا')
        self.assertContains(page, 'تفسير محتمل')
        self.assertContains(page, 'class="info-tip"')
        self.assertNotContains(page, 'بصمة البيانات:')
        self.assertNotContains(page, 'متطلب تشغيلي:')

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

    def test_page_has_public_read_only_view(self):
        self.assertEqual(self.client.get(self.url).status_code, 200)
        non_staff = get_user_model().objects.create(username='student')
        self.client.force_login(non_staff)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        staff = get_user_model().objects.create(username='staff', is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_scenario_compares_results_without_changing_capacity(self):
        self.client.force_login(self.admin)
        section = Section.objects.get(term=self.term, course__code='CS401', code='A')
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
        self.assertContains(page, 'المقترح في خط الأساس')
        self.assertContains(page, 'طلبات إضافية حصلت على مقعد')

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

    def test_public_result_hides_student_details_and_private_runs(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.url, {'term': self.term.pk})
        run = OptimizationRun.objects.get()
        self.client.logout()
        page = self.client.get(response['Location'])
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, 'EX002')
        self.assertNotContains(page, 'تصدير CSV')
        private_term = AcademicTerm.objects.create(name='فصل خاص')
        private_run = OptimizationRun.objects.create(
            term=private_term, status=OptimizationRun.Status.COMPLETED,
        )
        self.assertEqual(self.client.get(self.url, {'run': private_run.pk}).status_code, 404)
        self.assertEqual(self.client.get(reverse('optimizer:export_csv', args=[run.pk])).status_code, 302)

    def test_new_section_and_move_time_are_virtual(self):
        self.client.force_login(self.admin)
        course = Course.objects.get(code='CS401')
        response = self.client.post(self.url, {
            'action': 'new_section', 'term': self.term.pk, 'course': course.pk,
            'capacity': 5, 'weekday': 3, 'start_time': '13:00', 'end_time': '14:00',
        })
        self.assertEqual(response.status_code, 302)
        run = OptimizationRun.objects.latest('pk')
        self.assertEqual(run.scenario_type, OptimizationRun.Scenario.NEW_SECTION)
        self.assertGreaterEqual(run.after_assigned, run.baseline_after_assigned)
        self.assertEqual(Section.objects.filter(term=self.term).count(), 3)
        section = Section.objects.get(term=self.term, course=course, code='A')
        old_slot = list(section.meeting_times.values_list('weekday', 'start_time', 'end_time'))
        response = self.client.post(self.url, {
            'action': 'move_time', 'term': self.term.pk, 'section': section.pk,
            'weekday': 3, 'start_time': '13:00', 'end_time': '14:00',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(list(section.meeting_times.values_list('weekday', 'start_time', 'end_time')), old_slot)

    def test_saved_rows_do_not_change_with_live_student_name(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.url, {'term': self.term.pk})
        run = OptimizationRun.objects.get()
        saved_name = run.proposal_snapshot[0]['student_name']
        student = Student.objects.get(full_name=saved_name)
        student.full_name = 'اسم تغيّر بعد التشغيل'
        student.save(update_fields=['full_name'])
        page = self.client.get(response['Location'])
        self.assertContains(page, saved_name)
        self.assertNotContains(page, 'اسم تغيّر بعد التشغيل')

    def test_csv_export_uses_saved_rows_and_escapes_formula(self):
        self.client.force_login(self.admin)
        self.client.post(self.url, {'term': self.term.pk})
        run = OptimizationRun.objects.get()
        rows = run.proposal_snapshot
        rows[0]['student_name'] = '=1+1'
        run.proposal_snapshot = rows
        run.save(update_fields=['proposal_snapshot'])
        response = self.client.get(reverse('optimizer:export_csv', args=[run.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn("'=1+1", response.content.decode('utf-8-sig'))

    def test_reset_requires_permission_and_creates_new_example(self):
        reset_url = reverse('academics:home')
        self.assertEqual(self.client.post(reset_url, {'action': 'reset_example'}).status_code, 403)
        self.client.force_login(self.admin)
        response = self.client.post(reset_url, {'action': 'reset_example'})
        self.assertEqual(response.status_code, 302)
        latest = AcademicTerm.objects.order_by('-pk').first()
        self.assertTrue(latest.is_example)
        self.assertEqual(CourseRequest.objects.filter(term=latest).count(), 204)
        self.assertTrue(OptimizationRun.objects.filter(term=latest).exists())


class AcademicConstraintTests(TestCase):
    def test_prerequisite_and_credit_limit(self):
        term = AcademicTerm.objects.create(name='فصل القيود')
        foundation = Course.objects.create(code='BASE', title='أساس', credit_hours=3)
        advanced = Course.objects.create(code='ADV', title='متقدم', credit_hours=3)
        advanced.prerequisites.add(foundation)
        section = Section.objects.create(term=term, course=advanced, code='A', capacity=2)
        MeetingTime.objects.create(section=section, weekday=0, start_time=time(9), end_time=time(10))
        missing = Student.objects.create(student_number='M1', full_name='ناقص المتطلب')
        limited = Student.objects.create(student_number='M2', full_name='حد الساعات', max_credit_hours=2)
        eligible = Student.objects.create(student_number='M3', full_name='مستوفٍ')
        limited.completed_courses.add(foundation)
        eligible.completed_courses.add(foundation)
        requests = {
            student.pk: CourseRequest.objects.create(term=term, student=student, course=advanced)
            for student in (missing, limited, eligible)
        }
        result = solve_term(term)
        assigned = {item.request_id for item in result.assignments}
        self.assertEqual(assigned, {requests[eligible.pk].pk})
        reasons = diagnose_unassigned(term, result)
        self.assertEqual(reasons[str(requests[missing.pk].pk)], 'المتطلبات السابقة غير مكتملة')
        self.assertEqual(reasons[str(requests[limited.pk].pk)], 'تجاوز حد الساعات')

    def test_fairness_covers_two_students_before_second_course(self):
        term = AcademicTerm.objects.create(name='فصل العدالة')
        student_a = Student.objects.create(student_number='F1', full_name='الأول')
        student_b = Student.objects.create(student_number='F2', full_name='الثاني')
        for code in ('F101', 'F102'):
            course = Course.objects.create(code=code, title=code)
            section = Section.objects.create(term=term, course=course, code='A', capacity=1)
            MeetingTime.objects.create(section=section, weekday=0, start_time=time(9), end_time=time(10))
            CourseRequest.objects.create(term=term, student=student_a, course=course)
            CourseRequest.objects.create(term=term, student=student_b, course=course)
        result = solve_term(term)
        self.assertEqual(len(result.assignments), 2)
        self.assertEqual(set(result.covered_student_ids), {student_a.pk, student_b.pk})
