from datetime import time
from random import Random

from django.core.management.base import BaseCommand
from django.db import transaction

from academics.models import (
    AcademicTerm,
    Course,
    CourseRequest,
    Enrollment,
    MeetingTime,
    Section,
    Student,
)


EXAMPLE_TERM_NAME = "فصل توازن التجريبي 2026"
LARGE_EXAMPLE_TERM_NAME = "فصل توازن الموسع 2026"

EXAMPLE_COURSES = (
    ("AI401", "الذكاء الاصطناعي", MeetingTime.Weekday.SUNDAY, MeetingTime.Weekday.TUESDAY, time(9), time(10)),
    ("NET431", "أمن شبكات الحاسب", MeetingTime.Weekday.MONDAY, MeetingTime.Weekday.WEDNESDAY, time(9), time(10)),
    ("WEB350", "هندسة الويب", MeetingTime.Weekday.SUNDAY, MeetingTime.Weekday.TUESDAY, time(10), time(11)),
    ("DB341", "إدارة نظم قواعد البيانات", MeetingTime.Weekday.MONDAY, MeetingTime.Weekday.WEDNESDAY, time(10), time(11)),
    ("PROJ499", "مشروع التخرج", MeetingTime.Weekday.SUNDAY, MeetingTime.Weekday.THURSDAY, time(9, 30), time(10, 30)),
)
UNSCHEDULED_COURSE = ("COOP490", "التدريب التعاوني")


class Command(BaseCommand):
    help = "إضافة بيانات افتراضية قابلة لإعادة التشغيل لعرض توزيع الطلاب"

    def add_arguments(self, parser):
        parser.add_argument(
            "--large", action="store_true",
            help="إضافة 100 طالب وستة مقررات و204 طلبات في فصل مثال مستقل",
        )
        parser.add_argument("--term-name", default=LARGE_EXAMPLE_TERM_NAME, help="اسم نسخة المثال الموسع")

    def handle(self, *args, **options):
        with transaction.atomic():
            term, _ = AcademicTerm.objects.get_or_create(name=EXAMPLE_TERM_NAME, defaults={"is_example": True})
            if not term.is_example:
                term.is_example = True
                term.save(update_fields=["is_example"])

            courses = {}
            for code, title in (
                ("CS401", "الذكاء الاصطناعي التجريبي"),
                ("MATH201", "الرياضيات التجريبية"),
            ):
                courses[code], _ = Course.objects.get_or_create(
                    code=code, defaults={"title": title}
                )

            students = {}
            for number, name, graduating in (
                ("EX001", "طالب تجريبي مسجل", False),
                ("EX002", "طالب تجريبي متوقع تخرجه 1", True),
                ("EX003", "طالب تجريبي متوقع تخرجه 2", True),
                ("EX004", "طالب تجريبي 4", False),
                ("EX005", "طالب تجريبي 5", False),
                ("EX006", "طالب تجريبي 6", False),
            ):
                students[number], _ = Student.objects.get_or_create(
                    student_number=number,
                    defaults={
                        "full_name": name,
                        "expected_to_graduate": graduating,
                    },
                )

            sections = {}
            for course_code, section_code, capacity, weekday, start, end in (
                ("CS401", "A", 2, MeetingTime.Weekday.SUNDAY, time(9), time(10)),
                ("CS401", "B", 1, MeetingTime.Weekday.TUESDAY, time(9), time(10)),
                ("MATH201", "A", 2, MeetingTime.Weekday.SUNDAY, time(9, 30), time(10, 30)),
            ):
                section, _ = Section.objects.get_or_create(
                    term=term,
                    course=courses[course_code],
                    code=section_code,
                    defaults={"capacity": capacity},
                )
                sections[(course_code, section_code)] = section
                MeetingTime.objects.get_or_create(
                    section=section,
                    weekday=weekday,
                    start_time=start,
                    end_time=end,
                )

            requests = {}
            for student_number, course_code, required in (
                ("EX001", "CS401", False),
                ("EX002", "CS401", True),
                ("EX002", "MATH201", True),
                ("EX003", "CS401", True),
                ("EX004", "CS401", False),
                ("EX005", "MATH201", False),
                ("EX006", "MATH201", False),
            ):
                request, _ = CourseRequest.objects.get_or_create(
                    student=students[student_number],
                    course=courses[course_code],
                    term=term,
                    defaults={"required_for_graduation": required},
                )
                requests[(student_number, course_code)] = request

            Enrollment.objects.get_or_create(
                request=requests[("EX001", "CS401")],
                defaults={"section": sections[("CS401", "A")]},
            )

            if options["large"]:
                self.seed_large_example(options["term_name"])

        self.stdout.write(self.style.SUCCESS(
            f"البيانات التجريبية جاهزة: {term.name}. "
            "يمكن إعادة تشغيل الأمر دون تكرار السجلات."
        ))

    def seed_large_example(self, term_name=LARGE_EXAMPLE_TERM_NAME):
        """Create repeatable fictional data without changing existing records."""
        rng = Random(439446)
        term, _ = AcademicTerm.objects.get_or_create(name=term_name, defaults={"is_example": True})
        if not term.is_example:
            term.is_example = True
            term.save(update_fields=["is_example"])
        courses = []
        for code, title, first_day, second_day, start, end in EXAMPLE_COURSES:
            course, _ = Course.objects.get_or_create(code=code, defaults={"title": title})
            courses.append(course)
            for section_code, weekday in (("A", first_day), ("B", second_day)):
                section, _ = Section.objects.get_or_create(
                    term=term, course=course, code=section_code,
                    defaults={"capacity": 14},
                )
                MeetingTime.objects.get_or_create(
                    section=section, weekday=weekday,
                    start_time=start, end_time=end,
                )

        first_names = ("أحمد", "محمد", "عبدالله", "خالد", "عمر", "سلمان", "تركي", "يوسف", "فيصل", "راشد")
        father_names = ("علي", "ناصر", "فهد", "سعد", "حسن", "إبراهيم", "صالح", "ماجد", "عبدالعزيز", "بدر")
        family_names = ("القحطاني", "العتيبي", "الحربي", "الشمري", "الدوسري", "الغامدي", "الزهراني", "المطيري", "الخالدي", "السبيعي")
        names = rng.sample([
            f"{first} {father} {family}"
            for first in first_names for father in father_names for family in family_names
        ], 100)
        suffixes = rng.sample(range(100000, 1000000), 100)

        graduating_students = []
        for index, (name, suffix) in enumerate(zip(names, suffixes)):
            cohort = 439 + index % 8
            student_number = f"{cohort}{suffix}"
            student, _ = Student.objects.get_or_create(
                student_number=student_number,
                defaults={
                    "full_name": name,
                    "expected_to_graduate": cohort == 439,
                },
            )
            if cohort == 439:
                graduating_students.append(student)
            for course in rng.sample(courses, 2):
                CourseRequest.objects.get_or_create(
                    student=student, course=course, term=term,
                    defaults={
                        "required_for_graduation": cohort == 439 or course.code == "PROJ499",
                    },
                )

        # Four graduating students need a required course with no open section.
        unscheduled_course, _ = Course.objects.get_or_create(
            code=UNSCHEDULED_COURSE[0],
            defaults={"title": UNSCHEDULED_COURSE[1]},
        )
        for student in graduating_students[:4]:
            CourseRequest.objects.get_or_create(
                student=student, course=unscheduled_course, term=term,
                defaults={"required_for_graduation": True},
            )

        self.stdout.write(self.style.SUCCESS(
            f"البيانات الموسعة جاهزة: {term.name}، 100 طالب، 6 مقررات، 10 شعب، 204 طلبات."
        ))
