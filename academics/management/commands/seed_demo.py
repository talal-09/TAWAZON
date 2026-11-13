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


DEMO_TERM_NAME = "فصل توازن التجريبي 2026"
LARGE_DEMO_TERM_NAME = "فصل توازن الموسع 2026"

LARGE_COURSES = (
    ("DEMO-AI401", "الذكاء الاصطناعي", MeetingTime.Weekday.SUNDAY, MeetingTime.Weekday.TUESDAY, time(9), time(10)),
    ("DEMO-NET431", "أمن شبكات الحاسب", MeetingTime.Weekday.MONDAY, MeetingTime.Weekday.WEDNESDAY, time(9), time(10)),
    ("DEMO-WEB350", "هندسة الويب", MeetingTime.Weekday.SUNDAY, MeetingTime.Weekday.TUESDAY, time(10), time(11)),
    ("DEMO-DB341", "إدارة نظم قواعد البيانات", MeetingTime.Weekday.MONDAY, MeetingTime.Weekday.WEDNESDAY, time(10), time(11)),
    ("DEMO-PROJ499", "مشروع التخرج", MeetingTime.Weekday.SUNDAY, MeetingTime.Weekday.THURSDAY, time(9, 30), time(10, 30)),
)


class Command(BaseCommand):
    help = "إضافة بيانات افتراضية قابلة لإعادة التشغيل لعرض توزيع الطلاب"

    def add_arguments(self, parser):
        parser.add_argument(
            "--large", action="store_true",
            help="إضافة 100 طالب وخمسة مقررات في فصل تجريبي مستقل",
        )

    def handle(self, *args, **options):
        with transaction.atomic():
            term, _ = AcademicTerm.objects.get_or_create(name=DEMO_TERM_NAME)

            courses = {}
            for code, title in (
                ("DEMO-CS401", "الذكاء الاصطناعي التجريبي"),
                ("DEMO-MATH201", "الرياضيات التجريبية"),
            ):
                courses[code], _ = Course.objects.get_or_create(
                    code=code, defaults={"title": title}
                )

            students = {}
            for number, name, graduating in (
                ("DEMO001", "طالب تجريبي مسجل", False),
                ("DEMO002", "طالب تجريبي متوقع تخرجه 1", True),
                ("DEMO003", "طالب تجريبي متوقع تخرجه 2", True),
                ("DEMO004", "طالب تجريبي 4", False),
                ("DEMO005", "طالب تجريبي 5", False),
                ("DEMO006", "طالب تجريبي 6", False),
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
                ("DEMO-CS401", "A", 2, MeetingTime.Weekday.SUNDAY, time(9), time(10)),
                ("DEMO-CS401", "B", 1, MeetingTime.Weekday.TUESDAY, time(9), time(10)),
                ("DEMO-MATH201", "A", 2, MeetingTime.Weekday.SUNDAY, time(9, 30), time(10, 30)),
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
                ("DEMO001", "DEMO-CS401", False),
                ("DEMO002", "DEMO-CS401", True),
                ("DEMO002", "DEMO-MATH201", True),
                ("DEMO003", "DEMO-CS401", True),
                ("DEMO004", "DEMO-CS401", False),
                ("DEMO005", "DEMO-MATH201", False),
                ("DEMO006", "DEMO-MATH201", False),
            ):
                request, _ = CourseRequest.objects.get_or_create(
                    student=students[student_number],
                    course=courses[course_code],
                    term=term,
                    defaults={"required_for_graduation": required},
                )
                requests[(student_number, course_code)] = request

            Enrollment.objects.get_or_create(
                request=requests[("DEMO001", "DEMO-CS401")],
                defaults={"section": sections[("DEMO-CS401", "A")]},
            )

            if options["large"]:
                self.seed_large_demo()

        self.stdout.write(self.style.SUCCESS(
            f"البيانات التجريبية جاهزة: {term.name}. "
            "يمكن إعادة تشغيل الأمر دون تكرار السجلات."
        ))

    def seed_large_demo(self):
        """Create repeatable fictional data without changing existing records."""
        rng = Random(439446)
        term, _ = AcademicTerm.objects.get_or_create(name=LARGE_DEMO_TERM_NAME)
        courses = []
        for code, title, first_day, second_day, start, end in LARGE_COURSES:
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
            for course in rng.sample(courses, 2):
                CourseRequest.objects.get_or_create(
                    student=student, course=course, term=term,
                    defaults={
                        "required_for_graduation": cohort == 439 or course.code == "DEMO-PROJ499",
                    },
                )

        self.stdout.write(self.style.SUCCESS(
            f"البيانات الموسعة جاهزة: {term.name}، 100 طالب، 5 مقررات، 10 شعب، 200 طلب."
        ))
