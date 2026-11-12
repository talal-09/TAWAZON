from django.contrib import admin

from .models import OptimizationRun, ProposedEnrollment


@admin.register(OptimizationRun)
class OptimizationRunAdmin(admin.ModelAdmin):
    list_display = ('id', 'term', 'status', 'allow_new_sections', 'created_at')
    list_filter = ('term', 'status', 'allow_new_sections')
    list_select_related = ('term',)
    search_fields = ('=id', 'term__name')
    autocomplete_fields = ('term',)
    readonly_fields = ('status', 'created_at')


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
