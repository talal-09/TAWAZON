from django import forms

from .models import Course


class CourseForm(forms.ModelForm):
    class Meta:
        model = Course
        fields = ('code', 'title', 'credit_hours')
        widgets = {
            'code': forms.TextInput(attrs={'dir': 'ltr', 'maxlength': 20}),
        }

    def clean_code(self):
        return self.cleaned_data['code'].strip().upper()
