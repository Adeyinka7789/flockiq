import datetime

from django import forms

from apps.farm.flocks.models import Batch, MortalityLog, WeightRecord


class BatchCreateForm(forms.Form):
    farm_id = forms.UUIDField(widget=forms.HiddenInput(), required=False)
    house_id = forms.UUIDField(label="House")
    batch_name = forms.CharField(max_length=100, label="Batch Name")
    bird_type = forms.ChoiceField(
        choices=Batch.BirdType.choices,
        label="Bird Type",
        initial="broiler",
    )
    placement_date = forms.DateField(
        label="Placement Date",
        widget=forms.DateInput(attrs={"type": "date"}),
        initial=datetime.date.today,
    )
    initial_count = forms.IntegerField(
        min_value=1,
        label="Initial Count",
        widget=forms.NumberInput(attrs={"inputmode": "numeric"}),
    )
    breed_name = forms.CharField(
        max_length=100,
        label="Breed (optional)",
        required=False,
    )

    def clean_placement_date(self):
        value = self.cleaned_data.get("placement_date")
        if value and value > datetime.date.today():
            raise forms.ValidationError("Placement date cannot be in the future.")
        return value


class MortalityLogForm(forms.Form):
    date = forms.DateField(
        label="Date",
        widget=forms.DateInput(attrs={"type": "date"}),
        initial=datetime.date.today,
    )
    count = forms.IntegerField(
        min_value=1,
        label="Number of Birds",
        widget=forms.NumberInput(attrs={"inputmode": "numeric", "class": "text-2xl"}),
    )
    cause = forms.ChoiceField(
        choices=MortalityLog.Cause.choices,
        label="Cause",
        initial="unknown",
    )
    notes = forms.CharField(
        required=False,
        label="Notes",
        widget=forms.Textarea(attrs={"rows": 2}),
    )


class WeightRecordForm(forms.Form):
    sample_date = forms.DateField(
        label="Date",
        widget=forms.DateInput(attrs={"type": "date"}),
        initial=datetime.date.today,
    )
    sample_size = forms.IntegerField(
        min_value=1,
        label="Birds Weighed",
        widget=forms.NumberInput(attrs={"inputmode": "numeric"}),
    )
    avg_weight_kg = forms.DecimalField(
        max_digits=6,
        decimal_places=3,
        label="Average Weight (kg)",
    )
    min_weight_kg = forms.DecimalField(
        max_digits=6,
        decimal_places=3,
        label="Min Weight (kg)",
        required=False,
    )
    max_weight_kg = forms.DecimalField(
        max_digits=6,
        decimal_places=3,
        label="Max Weight (kg)",
        required=False,
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )


class BatchCloseForm(forms.Form):
    notes = forms.CharField(
        required=False,
        label="Closing Notes",
        widget=forms.Textarea(attrs={"rows": 3}),
    )
