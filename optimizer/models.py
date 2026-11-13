from django.db import models
from django.core.exceptions import ValidationError

from academics.models import AcademicTerm, CourseRequest, Section


class OptimizationRun(models.Model):
    class Scenario(models.TextChoices):
        BASELINE = 'baseline', 'توزيع أساسي'
        SEATS = 'seats', 'زيادة مقاعد'
        NEW_SECTION = 'new_section', 'شعبة جديدة'
        MOVE_TIME = 'move_time', 'تغيير موعد'

    class Status(models.TextChoices):
        PENDING = 'pending', 'بانتظار التشغيل'
        COMPLETED = 'completed', 'مكتمل'
        FAILED = 'failed', 'فشل'

    term = models.ForeignKey(AcademicTerm, on_delete=models.PROTECT, related_name='optimization_runs', verbose_name='الفصل الدراسي')
    allow_new_sections = models.BooleanField('السماح بشعب جديدة', default=False)
    status = models.CharField('الحالة', max_length=10, choices=Status.choices, default=Status.PENDING)
    scenario_type = models.CharField('نوع السيناريو', max_length=20, choices=Scenario.choices, default=Scenario.BASELINE)
    scenario_settings = models.JSONField('إعدادات السيناريو', default=dict, blank=True)
    total_requests = models.PositiveIntegerField('إجمالي الطلبات', default=0)
    before_assigned = models.PositiveIntegerField('المسند قبل التحسين', default=0)
    after_assigned = models.PositiveIntegerField('المسند بعد التحسين', default=0)
    scenario_section = models.ForeignKey(Section, on_delete=models.PROTECT, null=True, blank=True, related_name='scenario_runs', verbose_name='شعبة السيناريو')
    extra_seats = models.PositiveIntegerField('المقاعد الافتراضية الإضافية', default=0)
    baseline_after_assigned = models.PositiveIntegerField('المسند دون زيادة المقاعد', default=0)
    baseline_graduating_assigned = models.PositiveIntegerField('طلبات الخريجين المسندة دون زيادة', default=0)
    after_graduating_assigned = models.PositiveIntegerField('طلبات الخريجين المسندة بعد الزيادة', default=0)
    newly_assigned_count = models.PositiveIntegerField('طلبات استفادت من السيناريو', default=0)
    baseline_covered_students = models.PositiveIntegerField('طلاب لديهم مقرر في الأساس', default=0)
    after_covered_students = models.PositiveIntegerField('طلاب لديهم مقرر بعد السيناريو', default=0)
    baseline_solver_status = models.CharField('حالة حل الأساس', max_length=20, blank=True)
    solver_status = models.CharField('حالة الحل', max_length=20, blank=True)
    recommendations = models.JSONField('توصيات الشعب', default=list, blank=True)
    proposal_snapshot = models.JSONField('نسخة التسجيلات المقترحة', default=list, blank=True)
    unassigned_snapshot = models.JSONField('نسخة الطلبات غير الموزعة', default=list, blank=True)
    data_fingerprint = models.CharField('بصمة البيانات', max_length=64, blank=True)
    solver_version = models.CharField('نسخة سياسة المحرك', max_length=20, blank=True)
    unassigned_request_ids = models.JSONField('معرفات الطلبات غير المسندة', default=list, blank=True)
    unassigned_reasons = models.JSONField('أسباب عدم التوزيع', default=dict, blank=True)
    created_at = models.DateTimeField('تاريخ الإنشاء', auto_now_add=True)

    class Meta:
        verbose_name = 'تشغيل التحسين'
        verbose_name_plural = 'تشغيلات التحسين'
        ordering = ['-created_at']

    def __str__(self):
        return f'تشغيل {self.pk} - {self.term.name} ({self.get_status_display()})'


class ProposedEnrollment(models.Model):
    run = models.ForeignKey(OptimizationRun, on_delete=models.CASCADE, related_name='proposed_enrollments', verbose_name='تشغيل التحسين')
    request = models.ForeignKey(CourseRequest, on_delete=models.PROTECT, related_name='proposals', verbose_name='طلب التسجيل')
    section = models.ForeignKey(Section, on_delete=models.PROTECT, related_name='proposals', verbose_name='الشعبة المقترحة', null=True, blank=True)
    virtual_section_label = models.CharField('الشعبة الافتراضية', max_length=80, blank=True)

    class Meta:
        verbose_name = 'تسجيل مقترح'
        verbose_name_plural = 'التسجيلات المقترحة'
        constraints = [
            models.UniqueConstraint(fields=['run', 'request'], name='unique_proposal_per_run_request'),
        ]

    def clean(self):
        super().clean()
        if not self.run_id or not self.request_id:
            return
        if not self.section_id:
            if not self.virtual_section_label or self.run.scenario_type != OptimizationRun.Scenario.NEW_SECTION:
                raise ValidationError('يجب تحديد شعبة فعلية أو شعبة جديدة افتراضية.')
            return
        if self.request.term_id != self.run.term_id or self.request.term_id != self.section.term_id:
            raise ValidationError('يجب أن يكون طلب التسجيل والشعبة من فصل تشغيل التحسين نفسه.')
        if self.request.course_id != self.section.course_id:
            raise ValidationError('يجب أن تطابق الشعبة المقرر المطلوب.')

    def __str__(self):
        return f'{self.request} - {self.section.code if self.section_id else self.virtual_section_label}'
