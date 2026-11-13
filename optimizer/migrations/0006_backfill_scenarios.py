from django.db import migrations


def mark_existing_scenarios(apps, schema_editor):
    Run = apps.get_model('optimizer', 'OptimizationRun')
    Run.objects.filter(scenario_section__isnull=False, extra_seats__gt=0).update(scenario_type='seats')


class Migration(migrations.Migration):
    dependencies = [('optimizer', '0005_optimizationrun_after_covered_students_and_more')]
    operations = [migrations.RunPython(mark_existing_scenarios, migrations.RunPython.noop)]
