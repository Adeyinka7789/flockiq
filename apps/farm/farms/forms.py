from django import forms

from .models import Farm, House

_LAT_MIN, _LAT_MAX = 4.0, 14.0
_LNG_MIN, _LNG_MAX = 2.7, 15.0


class FarmCreateForm(forms.Form):
    name = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={"placeholder": "e.g. Sunrise Poultry Farm"}),
    )
    location = forms.CharField(
        max_length=300,
        widget=forms.TextInput(attrs={"placeholder": "e.g. Ibadan, Oyo State"}),
    )
    latitude = forms.DecimalField(
        max_digits=10,
        decimal_places=7,
        widget=forms.NumberInput(attrs={"step": "0.0000001", "placeholder": "e.g. 7.3775"}),
    )
    longitude = forms.DecimalField(
        max_digits=10,
        decimal_places=7,
        widget=forms.NumberInput(attrs={"step": "0.0000001", "placeholder": "e.g. 3.9470"}),
    )
    farm_type = forms.ChoiceField(choices=Farm.FarmType.choices)

    def clean_latitude(self):
        lat = self.cleaned_data.get("latitude")
        if lat is not None and not (_LAT_MIN <= float(lat) <= _LAT_MAX):
            raise forms.ValidationError(
                f"Latitude must be between {_LAT_MIN} and {_LAT_MAX} (Nigeria bounding box)."
            )
        return lat

    def clean_longitude(self):
        lng = self.cleaned_data.get("longitude")
        if lng is not None and not (_LNG_MIN <= float(lng) <= _LNG_MAX):
            raise forms.ValidationError(
                f"Longitude must be between {_LNG_MIN} and {_LNG_MAX} (Nigeria bounding box)."
            )
        return lng


class HouseCreateForm(forms.Form):
    name = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={"placeholder": "e.g. House A"}),
    )
    capacity = forms.IntegerField(
        min_value=1,
        widget=forms.NumberInput(attrs={"placeholder": "e.g. 5000"}),
    )
    house_type = forms.ChoiceField(choices=House.HouseType.choices)
