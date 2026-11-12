from django.contrib import admin

from .models import AcademicTerm, Course, CourseRequest, Enrollment, MeetingTime, Section, Student


@admin.register(AcademicTerm)
class AcademicTermAdmin(admin.ModelAdmin):
    search_fields = ('name',)


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ('student_number', 'full_name', 'expected_to_graduate')
    list_filter = ('expected_to_graduate',)
    search_fields = ('student_number', 'full_name')


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ('code', 'title')
    search_fields = ('code', 'title')


class MeetingTimeInline(admin.TabularInline):
    model = MeetingTime
    extra = 0


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    list_display = ('code', 'course', 'term', 'capacity')
    list_filter = ('term',)
    list_select_related = ('course', 'term')
    search_fields = ('code', 'course__code', 'course__title')
    autocomplete_fields = ('course', 'term')
    inlines = (MeetingTimeInline,)


@admin.register(MeetingTime)
class MeetingTimeAdmin(admin.ModelAdmin):
    list_display = ('section', 'weekday', 'start_time', 'end_time')
    list_filter = ('weekday', 'section__term')
    list_select_related = ('section__course', 'section__term')
    search_fields = ('section__code', 'section__course__code')
    autocomplete_fields = ('section',)


@admin.register(CourseRequest)
class CourseRequestAdmin(admin.ModelAdmin):
    list_display = ('student', 'course', 'term', 'required_for_graduation')
    list_filter = ('term', 'required_for_graduation', 'student__expected_to_graduate')
    list_select_related = ('student', 'course', 'term')
    search_fields = ('student__student_number', 'student__full_name', 'course__code')
    autocomplete_fields = ('student', 'course', 'term')


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ('request', 'section')
    list_filter = ('section__term',)
    list_select_related = (
        'request__student', 'request__course', 'request__term',
        'section__course', 'section__term',
    )
    search_fields = ('request__student__student_number', 'request__course__code', 'section__code')
    autocomplete_fields = ('request', 'section')
