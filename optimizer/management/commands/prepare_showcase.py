"""Create the reproducible, public read-only hackathon example."""

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from academics.management.commands.seed_example import LARGE_EXAMPLE_TERM_NAME
from academics.models import AcademicTerm, Section
from optimizer.models import OptimizationRun
from optimizer.services.results import fingerprint_term, save_result
from optimizer.services.solver import POLICY_VERSION, recommend_seat_increases, solve_term


class Command(BaseCommand):
    help = "إعداد بيانات ونتيجة عرض محفوظة دون تكرار التشغيل إذا لم تتغير البيانات"

    def handle(self, *args, **options):
        call_command("seed_example", large=True, verbosity=0)
        term = AcademicTerm.objects.get(name=LARGE_EXAMPLE_TERM_NAME)
        fingerprint = fingerprint_term(term)
        existing = OptimizationRun.objects.filter(
            term=term, scenario_type=OptimizationRun.Scenario.SEATS,
            data_fingerprint=fingerprint, extra_seats=10, solver_version=POLICY_VERSION,
            status=OptimizationRun.Status.COMPLETED,
        ).first()
        latest_showcase = OptimizationRun.objects.filter(
            status=OptimizationRun.Status.COMPLETED,
            term__is_example=True,
            scenario_type=OptimizationRun.Scenario.SEATS,
        ).first()
        if existing and latest_showcase and existing.pk == latest_showcase.pk:
            self.stdout.write(self.style.SUCCESS(f"نتيجة العرض جاهزة: تشغيل #{existing.pk}"))
            return
        baseline = solve_term(term)
        if baseline.status not in {"OPTIMAL", "FEASIBLE"}:
            raise CommandError(f"تعذر حساب خط الأساس: {baseline.status}")
        section = Section.objects.get(term=term, course__code="PROJ499", code="A")
        scenario = solve_term(
            term, seat_increases={section.pk: 10},
            protected_request_ids={item.request_id for item in baseline.assignments},
        )
        if scenario.status not in {"OPTIMAL", "FEASIBLE"}:
            raise CommandError(f"تعذر حساب السيناريو: {scenario.status}")
        run = save_result(
            term, scenario, baseline_result=baseline,
            scenario_type=OptimizationRun.Scenario.SEATS,
            scenario_section=section, extra_seats=10,
            scenario_settings={"section": str(section), "extra_seats": 10},
            recommendations=recommend_seat_increases(term, baseline),
        )
        self.stdout.write(self.style.SUCCESS(
            f"نتيجة العرض #{run.pk}: {run.baseline_after_assigned} → {run.after_assigned} من {run.total_requests}"
        ))
