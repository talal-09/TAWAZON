from django import forms

from academics.models import AcademicTerm, Section


class OptimizationForm(forms.Form):
    term = forms.ModelChoiceField(
        label='الفصل الدراسي',
        queryset=AcademicTerm.objects.order_by('name'),
        empty_label='اختر الفصل الدراسي',
    )


class ScenarioForm(OptimizationForm):
    section = forms.ModelChoiceField(
        label='الشعبة التي تزيد سعتها',
        queryset=Section.objects.select_related('course', 'term').order_by('term__name', 'course__code', 'code'),
        empty_label='اختر الشعبة',
    )
    extra_seats = forms.IntegerField(
        label='مقاعد إضافية', min_value=1, max_value=50,
        widget=forms.NumberInput(attrs={'min': 1, 'max': 50}),
    )

    def clean(self):
        cleaned = super().clean()
        term = cleaned.get('term')
        section = cleaned.get('section')
        if term and section and section.term_id != term.pk:
            self.add_error('section', 'الشعبة يجب أن تتبع الفصل الدراسي المحدد.')
        return cleaned
