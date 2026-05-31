import datetime

from django import forms

from .models import FEED_TYPE_CHOICES


class FeedLogForm(forms.Form):
    record_date = forms.DateField(
        initial=datetime.date.today,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    feed_type = forms.ChoiceField(choices=FEED_TYPE_CHOICES)
    quantity_kg = forms.DecimalField(min_value=0.01, max_digits=8, decimal_places=2)
    cost_per_kg = forms.DecimalField(
        min_value=0, max_digits=10, decimal_places=2, required=False
    )
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def clean_record_date(self):
        value = self.cleaned_data["record_date"]
        if value > datetime.date.today():
            raise forms.ValidationError("Record date cannot be in the future.")
        return value
