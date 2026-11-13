from django.shortcuts import render

from optimizer.models import OptimizationRun


def home(request):
    showcase = OptimizationRun.objects.filter(
        status=OptimizationRun.Status.COMPLETED,
        term__is_example=True,
    ).exclude(scenario_type=OptimizationRun.Scenario.BASELINE).select_related('term').first()
    return render(request, 'core/home.html', {'showcase': showcase})
