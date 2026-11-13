from django import forms

from academics.models import AcademicTerm, Course, CourseRequest, MeetingTime, Section


class OptimizationForm(forms.Form):
    term = forms.ModelChoiceField(
        label='الفصل الدراسي',
        queryset=AcademicTerm.objects.order_by('name'),
        empty_label='اختر الفصل الدراسي',
    )

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('auto_id', 'id_baseline_%s')
        super().__init__(*args, **kwargs)


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

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('auto_id', 'id_scenario_%s')
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        term = cleaned.get('term')
        section = cleaned.get('section')
        if term and section and section.term_id != term.pk:
            self.add_error('section', 'الشعبة يجب أن تتبع الفصل الدراسي المحدد.')
        return cleaned


class NewSectionForm(OptimizationForm):
    course = forms.ModelChoiceField(label='المقرر', queryset=Course.objects.order_by('code'))
    capacity = forms.IntegerField(label='سعة الشعبة الجديدة', min_value=1, max_value=50)
    weekday = forms.ChoiceField(label='يوم المحاضرة', choices=MeetingTime.Weekday.choices)
    start_time = forms.TimeField(label='بداية المحاضرة', widget=forms.TimeInput(attrs={'type': 'time'}))
    end_time = forms.TimeField(label='نهاية المحاضرة', widget=forms.TimeInput(attrs={'type': 'time'}))

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('auto_id', 'id_new_section_%s')
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        term, course = cleaned.get('term'), cleaned.get('course')
        if term and course and not CourseRequest.objects.filter(term=term, course=course).exists():
            self.add_error('course', 'لا توجد طلبات لهذا المقرر في الفصل المحدد.')
        start, end = cleaned.get('start_time'), cleaned.get('end_time')
        if start and end and start >= end:
            self.add_error('end_time', 'وقت النهاية يجب أن يكون بعد البداية.')
        return cleaned


class MoveTimeForm(OptimizationForm):
    section = forms.ModelChoiceField(label='الشعبة', queryset=Section.objects.select_related('course', 'term').order_by('term__name', 'course__code', 'code'))
    weekday = forms.ChoiceField(label='اليوم الجديد', choices=MeetingTime.Weekday.choices)
    start_time = forms.TimeField(label='وقت البداية الجديد', widget=forms.TimeInput(attrs={'type': 'time'}))
    end_time = forms.TimeField(label='وقت النهاية الجديد', widget=forms.TimeInput(attrs={'type': 'time'}))

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('auto_id', 'id_move_time_%s')
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        term, section = cleaned.get('term'), cleaned.get('section')
        if term and section and section.term_id != term.pk:
            self.add_error('section', 'الشعبة يجب أن تتبع الفصل الدراسي المحدد.')
        if section and section.meeting_times.count() != 1:
            self.add_error('section', 'تغيير الموعد يدعم الشعب ذات محاضرة واحدة فقط.')
        start, end = cleaned.get('start_time'), cleaned.get('end_time')
        if start and end and start >= end:
            self.add_error('end_time', 'وقت النهاية يجب أن يكون بعد البداية.')
        return cleaned
