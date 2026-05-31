import datetime

from django import forms


class WaterLogForm(forms.Form):
    record_date = forms.DateField(
        initial=datetime.date.today,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    litres_consumed = forms.DecimalField(min_value=0, max_digits=8, decimal_places=2)
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def clean_record_date(self):
        value = self.cleaned_data["record_date"]
        if value > datetime.date.today():
            raise forms.ValidationError("Record date cannot be in the future.")
        return value
