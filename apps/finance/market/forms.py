from django import forms

from .models import FeedPriceReport, NIGERIAN_STATE_CHOICES


def _apply_country_state_field(form, country):
    """Swap the `state` field to free text for non-Nigerian orgs.

    Nigeria keeps the validated dropdown (NIGERIAN_STATE_CHOICES); every other
    country gets a plain text input — we don't maintain per-country state
    catalogues, and country-level scoping is sufficient (see plan, Step 4).
    """
    if country and country != "Nigeria":
        form.fields["state"] = forms.CharField(max_length=100)


class FeedPriceSubmitForm(forms.Form):
    feed_type = forms.ChoiceField(choices=FeedPriceReport.FeedType.choices)
    brand = forms.ChoiceField(choices=FeedPriceReport.Brand.choices)
    brand_other = forms.CharField(required=False, max_length=100)
    price_per_25kg_bag = forms.DecimalField(
        min_value=1000,
        max_value=500000,
        decimal_places=2,
        error_messages={"min_value": "Price must be at least ₦1,000"},
    )
    state = forms.ChoiceField(choices=NIGERIAN_STATE_CHOICES)
    lga = forms.CharField(required=False, max_length=100)

    def __init__(self, *args, country="Nigeria", **kwargs):
        super().__init__(*args, **kwargs)
        _apply_country_state_field(self, country)

    def clean(self):
        cleaned_data = super().clean()
        brand = cleaned_data.get("brand")
        brand_other = cleaned_data.get("brand_other", "").strip()
        if brand == FeedPriceReport.Brand.OTHER and not brand_other:
            self.add_error("brand_other", "Please specify the brand name.")
        return cleaned_data


class HatcheryReviewForm(forms.Form):
    hatchery_id = forms.IntegerField(widget=forms.HiddenInput)
    batch_id = forms.UUIDField(required=False, widget=forms.HiddenInput)
    doc_quality_rating = forms.IntegerField(min_value=1, max_value=5)
    survival_rate_pct = forms.DecimalField(min_value=0, max_value=100, decimal_places=2)
    delivery_reliability = forms.IntegerField(min_value=1, max_value=5)
    overall_rating = forms.IntegerField(min_value=1, max_value=5)
    comment = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    batch_size = forms.IntegerField(min_value=1)
    purchase_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    price_per_doc = forms.DecimalField(min_value=0, decimal_places=2)


class SuggestHatcheryForm(forms.Form):
    BIRD_TYPE_CHOICES = [
        ("broiler", "Broiler"),
        ("layer", "Layer"),
        ("noiler", "Noiler"),
    ]

    name = forms.CharField(max_length=200)
    state = forms.ChoiceField(choices=NIGERIAN_STATE_CHOICES)
    lga = forms.CharField(required=False, max_length=100)
    address = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    phone = forms.CharField(required=False, max_length=20)
    website = forms.URLField(required=False, assume_scheme="https")
    bird_types = forms.MultipleChoiceField(
        choices=BIRD_TYPE_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, country="Nigeria", **kwargs):
        super().__init__(*args, **kwargs)
        _apply_country_state_field(self, country)
