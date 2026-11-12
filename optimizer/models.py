from django.db import models
from django.core.exceptions import ValidationError

from academics.models import AcademicTerm, CourseRequest, Section


class OptimizationRun(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'بانتظار التشغيل'
        COMPLETED = 'completed', 'مكتمل'
        FAILED = 'failed', 'فشل'

    term = models.ForeignKey(AcademicTerm, on_delete=models.PROTECT, related_name='optimization_runs', verbose_name='الفصل الدراسي')
    allow_new_sections = models.BooleanField('السماح بشعب جديدة', default=False)
    status = models.CharField('الحالة', max_length=10, choices=Status.choices, default=Status.PENDING)
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
    section = models.ForeignKey(Section, on_delete=models.PROTECT, related_name='proposals', verbose_name='الشعبة المقترحة')

    class Meta:
        verbose_name = 'تسجيل مقترح'
        verbose_name_plural = 'التسجيلات المقترحة'
        constraints = [
            models.UniqueConstraint(fields=['run', 'request'], name='unique_proposal_per_run_request'),
        ]

    def clean(self):
        super().clean()
        if not self.run_id or not self.request_id or not self.section_id:
            return
        if self.request.term_id != self.run.term_id or self.request.term_id != self.section.term_id:
            raise ValidationError('يجب أن يكون طلب التسجيل والشعبة من فصل تشغيل التحسين نفسه.')
        if self.request.course_id != self.section.course_id:
            raise ValidationError('يجب أن تطابق الشعبة المقرر المطلوب.')

    def __str__(self):
        return f'{self.request} - {self.section.code}'
