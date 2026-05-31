import datetime

from django import forms


class EggProductionLogForm(forms.Form):
    record_date = forms.DateField(
        initial=datetime.date.today,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-input"}),
    )
    total_eggs = forms.IntegerField(
        min_value=0,
        widget=forms.NumberInput(attrs={"class": "form-input", "inputmode": "numeric"}),
    )
    grade_a = forms.IntegerField(
        min_value=0,
        required=False,
        initial=0,
        widget=forms.NumberInput(attrs={"class": "form-input", "inputmode": "numeric"}),
    )
    grade_b = forms.IntegerField(
        min_value=0,
        required=False,
        initial=0,
        widget=forms.NumberInput(attrs={"class": "form-input", "inputmode": "numeric"}),
    )
    grade_c = forms.IntegerField(
        min_value=0,
        required=False,
        initial=0,
        widget=forms.NumberInput(attrs={"class": "form-input", "inputmode": "numeric"}),
    )
    broken = forms.IntegerField(
        min_value=0,
        required=False,
        initial=0,
        widget=forms.NumberInput(attrs={"class": "form-input", "inputmode": "numeric"}),
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2, "class": "form-input"}),
    )

    def clean(self):
        cleaned = super().clean()
        record_date = cleaned.get("record_date")
        total_eggs = cleaned.get("total_eggs")

        if record_date and record_date > datetime.date.today():
            self.add_error("record_date", "Record date cannot be in the future.")

        if total_eggs is not None:
            total_grades = (
                (cleaned.get("grade_a") or 0)
                + (cleaned.get("grade_b") or 0)
                + (cleaned.get("grade_c") or 0)
                + (cleaned.get("broken") or 0)
            )
            if total_grades > 0 and total_grades != total_eggs:
                raise forms.ValidationError(
                    f"Grade counts ({total_grades}) must equal total eggs ({total_eggs})."
                )

        return cleaned
