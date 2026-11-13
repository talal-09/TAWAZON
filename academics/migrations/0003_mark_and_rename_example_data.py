from django.db import migrations


def rename_existing_data(apps, schema_editor):
    AcademicTerm = apps.get_model('academics', 'AcademicTerm')
    Course = apps.get_model('academics', 'Course')
    Student = apps.get_model('academics', 'Student')

    AcademicTerm.objects.filter(name__in=[
        'فصل توازن التجريبي 2026', 'فصل توازن الموسع 2026',
    ]).update(is_example=True)

    for course in Course.objects.filter(code__startswith='DEMO-'):
        code = course.code.removeprefix('DEMO-')
        if Course.objects.filter(code=code).exclude(pk=course.pk).exists():
            code = f'TWZ-{code}'
        course.code = code
        course.save(update_fields=['code'])

    for student in Student.objects.filter(student_number__startswith='DEMO'):
        number = student.student_number.replace('DEMO', 'EX', 1)
        if Student.objects.filter(student_number=number).exclude(pk=student.pk).exists():
            number = f'TWZ-{number}'
        student.student_number = number
        student.save(update_fields=['student_number'])


class Migration(migrations.Migration):
    dependencies = [('academics', '0002_academicterm_is_example_course_credit_hours_and_more')]
    operations = [migrations.RunPython(rename_existing_data, migrations.RunPython.noop)]
