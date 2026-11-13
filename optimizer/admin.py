from django.contrib import admin

from .models import OptimizationRun, ProposedEnrollment


@admin.register(OptimizationRun)
class OptimizationRunAdmin(admin.ModelAdmin):
    list_display = ('id', 'term', 'status', 'scenario_section', 'extra_seats', 'before_assigned', 'after_assigned', 'created_at')
    list_filter = ('term', 'status', 'allow_new_sections')
    list_select_related = ('term', 'scenario_section')
    search_fields = ('=id', 'term__name')
    readonly_fields = (
        'term', 'allow_new_sections', 'status', 'created_at', 'total_requests', 'before_assigned',
        'after_assigned', 'scenario_section', 'extra_seats',
        'baseline_after_assigned', 'baseline_graduating_assigned',
        'after_graduating_assigned', 'newly_assigned_count',
        'unassigned_request_ids', 'unassigned_reasons',
    )

    def has_add_permission(self, request):
        return False


@admin.register(ProposedEnrollment)
class ProposedEnrollmentAdmin(admin.ModelAdmin):
    list_display = ('run', 'request', 'section')
    list_filter = ('run__term',)
    list_select_related = (
        'run__term', 'request__student', 'request__course', 'request__term',
        'section__course', 'section__term',
    )
    search_fields = ('=run__id', 'request__student__student_number', 'request__course__code')
    readonly_fields = ('run', 'request', 'section')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
