from django.db import models
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator


class AcademicTerm(models.Model):
    name = models.CharField('الفصل الدراسي', max_length=100, unique=True)
    is_example = models.BooleanField('بيانات مثال عامة', default=False)

    class Meta:
        verbose_name = 'فصل دراسي'
        verbose_name_plural = 'الفصول الدراسية'

    def __str__(self):
        return self.name


class Student(models.Model):
    student_number = models.CharField('الرقم الجامعي', max_length=30, unique=True)
    full_name = models.CharField('اسم الطالب', max_length=150)
    expected_to_graduate = models.BooleanField('متوقع تخرجه', default=False)
    max_credit_hours = models.PositiveSmallIntegerField('أقصى ساعات للفصل', default=18)
    completed_courses = models.ManyToManyField('Course', blank=True, related_name='students_completed', verbose_name='مقررات مكتملة')

    class Meta:
        verbose_name = 'طالب'
        verbose_name_plural = 'الطلاب'

    def __str__(self):
        return f'{self.full_name} ({self.student_number})'


class Course(models.Model):
    code = models.CharField('رمز المقرر', max_length=20, unique=True)
    title = models.CharField('اسم المقرر', max_length=150)
    credit_hours = models.PositiveSmallIntegerField('الساعات المعتمدة', default=3, validators=[MinValueValidator(1)])
    prerequisites = models.ManyToManyField('self', blank=True, symmetrical=False, related_name='opens_courses', verbose_name='المتطلبات السابقة')

    class Meta:
        verbose_name = 'مقرر'
        verbose_name_plural = 'المقررات'

    def __str__(self):
        return f'{self.code} - {self.title}'


class Section(models.Model):
    term = models.ForeignKey(AcademicTerm, on_delete=models.PROTECT, related_name='sections', verbose_name='الفصل الدراسي')
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name='sections', verbose_name='المقرر')
    code = models.CharField('رمز الشعبة', max_length=20)
    capacity = models.PositiveIntegerField('السعة', validators=[MinValueValidator(1)])

    class Meta:
        verbose_name = 'شعبة'
        verbose_name_plural = 'الشعب'
        constraints = [
            models.UniqueConstraint(fields=['term', 'course', 'code'], name='unique_section_per_term_course'),
            models.CheckConstraint(condition=models.Q(capacity__gte=1), name='section_capacity_at_least_one'),
        ]

    def __str__(self):
        return f'{self.course.code} - {self.code} ({self.term.name})'


class MeetingTime(models.Model):
    class Weekday(models.IntegerChoices):
        SUNDAY = 0, 'الأحد'
        MONDAY = 1, 'الإثنين'
        TUESDAY = 2, 'الثلاثاء'
        WEDNESDAY = 3, 'الأربعاء'
        THURSDAY = 4, 'الخميس'
        FRIDAY = 5, 'الجمعة'
        SATURDAY = 6, 'السبت'

    section = models.ForeignKey(Section, on_delete=models.CASCADE, related_name='meeting_times', verbose_name='الشعبة')
    weekday = models.IntegerField('اليوم', choices=Weekday.choices)
    start_time = models.TimeField('وقت البداية')
    end_time = models.TimeField('وقت النهاية')

    class Meta:
        verbose_name = 'موعد محاضرة'
        verbose_name_plural = 'مواعيد المحاضرات'
        constraints = [
            models.CheckConstraint(condition=models.Q(end_time__gt=models.F('start_time')), name='meeting_ends_after_start'),
        ]

    def __str__(self):
        return f'{self.section} - {self.get_weekday_display()} {self.start_time:%H:%M}-{self.end_time:%H:%M}'


class CourseRequest(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='course_requests', verbose_name='الطالب')
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name='requests', verbose_name='المقرر')
    term = models.ForeignKey(AcademicTerm, on_delete=models.PROTECT, related_name='course_requests', verbose_name='الفصل الدراسي')
    required_for_graduation = models.BooleanField('مطلوب للتخرج', default=False)

    class Meta:
        verbose_name = 'طلب تسجيل'
        verbose_name_plural = 'طلبات التسجيل'
        constraints = [
            models.UniqueConstraint(fields=['student', 'course', 'term'], name='unique_course_request_per_student_term'),
        ]

    def __str__(self):
        return f'{self.student.student_number} - {self.course.code} ({self.term.name})'


class Enrollment(models.Model):
    request = models.OneToOneField(CourseRequest, on_delete=models.CASCADE, related_name='enrollment', verbose_name='طلب التسجيل')
    section = models.ForeignKey(Section, on_delete=models.PROTECT, related_name='enrollments', verbose_name='الشعبة')

    class Meta:
        verbose_name = 'تسجيل حالي'
        verbose_name_plural = 'التسجيلات الحالية'

    def clean(self):
        super().clean()
        if not self.request_id or not self.section_id:
            return
        if self.request.course_id != self.section.course_id or self.request.term_id != self.section.term_id:
            raise ValidationError('يجب أن تطابق الشعبة مقرر طلب التسجيل وفصله الدراسي.')

    def __str__(self):
        return f'{self.request} - {self.section.code}'
