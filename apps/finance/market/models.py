import datetime

from django.conf import settings
from django.db import models

from apps.infrastructure.core.models import TenantAwareModel


class MarketPrice(TenantAwareModel):

    PRODUCT_TYPE_CHOICES = [
        ("eggs", "Eggs"),
        ("live_birds", "Live Birds"),
        ("spent_layers", "Spent Layers"),
        ("feed", "Feed"),
    ]

    date = models.DateField(default=datetime.date.today)
    product_type = models.CharField(max_length=20, choices=PRODUCT_TYPE_CHOICES)
    price_per_unit_kobo = models.IntegerField()
    unit = models.CharField(max_length=50)
    market_name = models.CharField(max_length=200)
    region = models.CharField(max_length=100, default="Lagos")
    recorded_by = models.ForeignKey(
        "accounts.CustomUser",
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        db_table = "market_marketprice"
        indexes = [
            models.Index(fields=["org", "product_type", "date"], name="market_price_org_type_date_idx"),
        ]

    def __str__(self):
        return f"{self.date} — {self.get_product_type_display()} @ ₦{self.price_per_unit_kobo / 100:,.2f}/{self.unit}"

    @property
    def price_per_unit_naira(self):
        return self.price_per_unit_kobo / 100


class SeasonalDemandIndex(models.Model):
    """Global reference data — admin-managed, no RLS."""

    PRODUCT_TYPE_CHOICES = [
        ("eggs", "Eggs"),
        ("live_birds", "Live Birds"),
    ]

    month = models.IntegerField()
    product_type = models.CharField(max_length=20, choices=PRODUCT_TYPE_CHOICES)
    demand_index = models.IntegerField()
    notes = models.CharField(max_length=300, blank=True)

    class Meta:
        db_table = "market_seasonaldemandindex"
        unique_together = [("month", "product_type")]

    def __str__(self):
        return f"Month {self.month} — {self.get_product_type_display()} index={self.demand_index}"


# ── Community Intelligence ────────────────────────────────────────────────────────

NIGERIAN_STATES = [
    "Abia", "Adamawa", "Akwa Ibom", "Anambra", "Bauchi", "Bayelsa",
    "Benue", "Borno", "Cross River", "Delta", "Ebonyi", "Edo", "Ekiti",
    "Enugu", "Gombe", "Imo", "Jigawa", "Kaduna", "Kano", "Katsina",
    "Kebbi", "Kogi", "Kwara", "Lagos", "Nasarawa", "Niger", "Ogun",
    "Ondo", "Osun", "Oyo", "Plateau", "Rivers", "Sokoto", "Taraba",
    "Yobe", "Zamfara", "FCT (Abuja)",
]

NIGERIAN_STATE_CHOICES = [(s, s) for s in NIGERIAN_STATES]


class FeedPriceReport(models.Model):
    """
    Crowdsourced feed price submitted by a farmer.
    Aggregated anonymously — individual submissions never shown.
    Not tenant-scoped — shared global data.
    """

    class FeedType(models.TextChoices):
        BROILER_STARTER = "broiler_starter", "Broiler Starter"
        BROILER_GROWER = "broiler_grower", "Broiler Grower"
        BROILER_FINISHER = "broiler_finisher", "Broiler Finisher"
        LAYERS_MASH = "layers_mash", "Layer's Mash"
        LAYERS_CHICK_MASH = "layers_chick_mash", "Layer Chick Mash"

    class Brand(models.TextChoices):
        TOPFEEDS = "topfeeds", "TopFeeds"
        CHIKUN = "chikun", "Chikun"
        ULTIMA = "ultima", "Ultima"
        ANIMAL_CARE = "animal_care", "Animal Care"
        HYBRID = "hybrid", "Hybrid"
        OTHER = "other", "Other"

    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="feed_price_reports",
    )
    org = models.ForeignKey(
        "tenants.Organization",
        on_delete=models.SET_NULL,
        null=True,
    )
    feed_type = models.CharField(max_length=30, choices=FeedType.choices)
    brand = models.CharField(max_length=30, choices=Brand.choices, default=Brand.OTHER)
    brand_other = models.CharField(max_length=100, blank=True)
    price_per_25kg_bag = models.DecimalField(
        max_digits=10, decimal_places=2,
        help_text="Price in Naira for a 25kg bag",
    )
    state = models.CharField(max_length=100)
    lga = models.CharField(max_length=100, blank=True, help_text="Local Government Area")
    reported_date = models.DateField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-reported_date"]
        indexes = [
            models.Index(fields=["feed_type", "state", "reported_date"]),
        ]

    def __str__(self):
        return f"{self.reported_date} — {self.get_feed_type_display()} ₦{self.price_per_25kg_bag} ({self.state})"


class Hatchery(models.Model):
    """Directory of DOC suppliers — curated and farmer-suggested."""

    name = models.CharField(max_length=200)
    state = models.CharField(max_length=100)
    lga = models.CharField(max_length=100, blank=True)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    website = models.URLField(blank=True)
    bird_types = models.JSONField(
        default=list,
        help_text='["broiler", "layer", "noiler"]',
    )
    is_verified = models.BooleanField(default=False)
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["state", "name"]
        verbose_name_plural = "hatcheries"

    def __str__(self):
        verified = " ✓" if self.is_verified else ""
        return f"{self.name} ({self.state}){verified}"


class HatcheryReview(models.Model):
    """Farmer's rating of a hatchery after completing a batch that used their DOCs."""

    hatchery = models.ForeignKey(
        Hatchery,
        on_delete=models.CASCADE,
        related_name="reviews",
    )
    batch = models.OneToOneField(
        "flocks.Batch",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="hatchery_review",
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
    )
    org = models.ForeignKey(
        "tenants.Organization",
        on_delete=models.SET_NULL,
        null=True,
    )
    doc_quality_rating = models.PositiveSmallIntegerField(
        help_text="1-5: Quality of day-old chicks",
    )
    survival_rate_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        help_text="% of DOCs that survived to harvest",
    )
    delivery_reliability = models.PositiveSmallIntegerField(
        help_text="1-5: On-time delivery reliability",
    )
    overall_rating = models.PositiveSmallIntegerField(
        help_text="1-5: Overall satisfaction",
    )
    comment = models.TextField(blank=True)
    batch_size = models.PositiveIntegerField(help_text="Number of DOCs purchased")
    purchase_date = models.DateField()
    price_per_doc = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        help_text="Price paid per DOC in Naira",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.hatchery.name} — {self.overall_rating}/5 by anon"
