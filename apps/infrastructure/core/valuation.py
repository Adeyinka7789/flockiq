"""
Flock valuation — estimates the current market worth of an active batch.

This is an *estimate*, not an appraisal. It exists to give farmers a rough
"what is this flock worth today" figure and to seed the Loss Documentation
Report (insurance supporting evidence). It is deliberately conservative and
self-documents its confidence so nobody mistakes it for a guaranteed value.

──────────────────────────────────────────────────────────────────────────────
HARDCODED PRICE ASSUMPTIONS — REVIEW PERIODICALLY
All of the constants below are *fallback* estimates used only when no real
MarketPrice data exists for the org. They were set in June 2026 against typical
Nigerian market rates. Update them as the market moves — a future maintainer
should treat these as "best guess", not gospel. When a fallback is used the
returned ``confidence`` drops to 'low' and ``price_source`` is 'fallback'.
──────────────────────────────────────────────────────────────────────────────
"""
from decimal import Decimal, ROUND_HALF_UP

from django.utils import timezone

# ── Fallback price assumptions (Naira) — set June 2026, see module docstring ──
# Live broiler weight price. Aligned with BroilerExitOptimizer's default of
# ₦1,850/kg (apps/health/analytics/exit_optimizer.py) so the two features agree.
FALLBACK_BROILER_PRICE_PER_KG = Decimal("1850")
# Point-of-lay pullet value. Nigerian POL pullets typically ₦2,500–₦3,500 (2026).
FALLBACK_POINT_OF_LAY_PER_BIRD = Decimal("2800")
# Generic per-bird value for unknown/other bird types — intentionally low.
FALLBACK_PER_BIRD = Decimal("2000")

# Documented standard broiler live-weight curve (grams of avg live weight by
# cycle day). Cobb-500-class growth — same anchor points used elsewhere in the
# app (flocks.views.COBB_500_STANDARD) with day 0 and a 56-day tail added so we
# can interpolate at any age. Used only when no WeightRecord exists.
_BROILER_WEIGHT_CURVE_G = {
    0: 42, 7: 170, 14: 400, 21: 780, 28: 1260,
    35: 1800, 42: 2400, 49: 2950, 56: 3300,
}

_TWOPLACES = Decimal("0.01")


def _money(value) -> Decimal:
    """Quantise to whole Naira (no kobo) for display-ready figures."""
    return Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def _interpolate_broiler_weight_g(day: int) -> int:
    """Linear-interpolate avg broiler live weight (grams) for a given cycle day."""
    days = sorted(_BROILER_WEIGHT_CURVE_G.keys())
    if day <= days[0]:
        return _BROILER_WEIGHT_CURVE_G[days[0]]
    if day >= days[-1]:
        return _BROILER_WEIGHT_CURVE_G[days[-1]]
    for i, d in enumerate(days):
        if day <= d:
            prev_d = days[i - 1]
            ratio = (day - prev_d) / (d - prev_d)
            lo = _BROILER_WEIGHT_CURVE_G[prev_d]
            hi = _BROILER_WEIGHT_CURVE_G[d]
            return int(lo + ratio * (hi - lo))
    return _BROILER_WEIGHT_CURVE_G[days[-1]]


class FlockValuationService:
    """
    Estimates the current market value of an active batch based on bird type,
    age, and current market prices.

    For broilers: value = current_count × age-adjusted weight estimate ×
        current price per kg (live weight).
    For layers: value = current_count × point-of-lay valuation per bird.

    Usage:
        FlockValuationService(batch).estimate_value()

    All DB reads are wrapped in their own tenant context, so the service is safe
    to call from anywhere that has a Batch instance — inside or outside an
    existing set_tenant_context() block (nested contexts compose via savepoints).
    """

    def __init__(self, batch):
        self.batch = batch

    # ── Public API ──────────────────────────────────────────────────────────

    def estimate_value(self) -> dict:
        """
        Returns a dict:
          {
            'estimated_value_naira': Decimal,
            'valuation_method': str,   # 'weight_based' | 'point_of_lay' |
                                       # 'fallback_per_bird'
            'price_per_unit': Decimal,
            'unit': str,               # 'kg' or 'bird'
            'current_count': int,
            'as_of': datetime,
            'confidence': str,         # 'high' | 'medium' | 'low'
            'price_source': str,       # 'market' | 'fallback'
            'notes': str,              # human-readable caveat, may be ''
          }
        """
        bird_type = getattr(self.batch, "bird_type", None)
        if bird_type == "broiler":
            return self._estimate_broiler_value()
        if bird_type == "layer":
            return self._estimate_layer_value()
        return self._fallback_estimate()

    # ── Broiler ───────────────────────────────────────────────────────────────

    def _estimate_broiler_value(self) -> dict:
        """
        Price source priority (see _broiler_market_price):
          1. Per-kg live-bird market price → weight-based valuation (most precise).
          2. Per-bird live-bird market price → count × per-bird price (real data,
             coarser; weight estimate is skipped entirely).
          3. Documented fallback ₦/kg → weight-based, confidence='low'.

        Weight (for the per-kg path) comes from the latest WeightRecord when
        available (actual), otherwise a documented breed growth curve (estimated).
        """
        price, price_unit, price_source = self._broiler_market_price()
        count = self.batch.current_count or 0

        # ── Per-bird market quote: use directly, no weight involved ──────────
        if price_unit == "bird":
            total = Decimal(count) * price
            return {
                "estimated_value_naira": _money(total),
                "valuation_method": "per_bird_market",
                "price_per_unit": _money(price),
                "unit": "bird",
                "current_count": count,
                "as_of": timezone.now(),
                "confidence": "medium",
                "price_source": "market",
                "weight_source": None,
                "notes": (
                    "Valued from a live-bird (per-bird) market price; "
                    "not weight-adjusted."
                ),
            }

        # ── Per-kg path (market or fallback): weight-based ──────────────────
        avg_weight_kg, weight_source = self._broiler_avg_weight_kg()
        total = Decimal(count) * avg_weight_kg * price

        # Confidence: high only when both inputs are real; low when both are
        # estimates; medium when exactly one is real.
        real_inputs = (weight_source == "actual") + (price_source == "market")
        confidence = {2: "high", 1: "medium", 0: "low"}[real_inputs]

        notes = ""
        if price_source == "fallback":
            notes = "Estimate based on general market rates (no recorded live-bird price)."
        elif weight_source == "estimated":
            notes = "Weight estimated from breed growth curve (no weight records logged)."

        return {
            "estimated_value_naira": _money(total),
            "valuation_method": "weight_based",
            "price_per_unit": _money(price),
            "unit": "kg",
            "current_count": count,
            "as_of": timezone.now(),
            "confidence": confidence,
            "price_source": price_source,
            "avg_weight_kg": avg_weight_kg.quantize(_TWOPLACES),
            "weight_source": weight_source,
            "notes": notes,
        }

    def _broiler_avg_weight_kg(self):
        """
        Returns (avg_weight_kg: Decimal, source: 'actual'|'estimated').

        Uses the most recent WeightRecord for the batch when present; otherwise
        interpolates the documented broiler growth curve at the current age.
        """
        from apps.infrastructure.core.rls import set_tenant_context

        try:
            from apps.farm.flocks.models import WeightRecord
            with set_tenant_context(self.batch.org):
                latest = (
                    WeightRecord.objects.filter(batch=self.batch)
                    .order_by("-sample_date")
                    .values_list("avg_weight_kg", flat=True)
                    .first()
                )
            if latest:
                return Decimal(latest), "actual"
        except Exception:
            pass

        day = max(0, self.batch.cycle_day or 0)
        grams = _interpolate_broiler_weight_g(day)
        return (Decimal(grams) / Decimal(1000)), "estimated"

    def _broiler_market_price(self):
        """
        Returns (price: Decimal, unit: 'kg'|'bird', source: 'market'|'fallback').

        Looks for the most recent live-bird MarketPrice for the org, preferring
        a per-kg quote (``unit`` contains 'kg') over a per-bird quote (``unit``
        contains 'bird') — per-kg is more precise because it accounts for the
        flock's current weight. MarketPrice is tenant-scoped, so the lookup is
        already org-isolated by RLS. Falls back to the documented ₦/kg estimate
        when no usable live-bird price exists.
        """
        from apps.infrastructure.core.rls import set_tenant_context

        try:
            from apps.finance.market.models import MarketPrice
            with set_tenant_context(self.batch.org):
                kg_row = (
                    MarketPrice.objects.filter(
                        product_type="live_birds",
                        unit__icontains="kg",
                    )
                    .order_by("-date")
                    .values_list("price_per_unit_kobo", flat=True)
                    .first()
                )
                if kg_row:
                    return (Decimal(kg_row) / Decimal(100)), "kg", "market"

                bird_row = (
                    MarketPrice.objects.filter(
                        product_type="live_birds",
                        unit__icontains="bird",
                    )
                    .order_by("-date")
                    .values_list("price_per_unit_kobo", flat=True)
                    .first()
                )
                if bird_row:
                    return (Decimal(bird_row) / Decimal(100)), "bird", "market"
        except Exception:
            pass

        return FALLBACK_BROILER_PRICE_PER_KG, "kg", "fallback"

    # ── Layer ─────────────────────────────────────────────────────────────────

    def _estimate_layer_value(self) -> dict:
        """
        Point-of-lay valuation per bird.

        v1 keeps this simple: every live layer is valued at the documented
        point-of-lay pullet price regardless of whether the batch is pre-lay or
        already laying. For a laying batch this is a conservative *baseline* —
        actual worth may be higher once egg revenue is factored in. We record
        that caveat in ``notes`` rather than guessing.
        """
        from apps.health.analytics.breed_benchmarks import get_benchmark

        benchmark = get_benchmark(
            getattr(self.batch, "breed_name", None), "layer"
        )
        lay_start_week = benchmark.get("optimal_lay_start_week", 18)
        point_of_lay_day = lay_start_week * 7

        count = self.batch.current_count or 0
        price_per_bird = FALLBACK_POINT_OF_LAY_PER_BIRD
        total = Decimal(count) * price_per_bird

        cycle_day = self.batch.cycle_day or 0
        is_laying = cycle_day >= point_of_lay_day
        if is_laying:
            notes = (
                "Valued at point-of-lay baseline; active laying value may be "
                "higher once egg production is factored in."
            )
        else:
            notes = "Pre-lay pullets valued at point-of-lay maturity estimate."

        # Known breed → documented benchmark drives the threshold; unknown breed
        # falls back to the generic layer default, so confidence is lower.
        breed_known = bool(getattr(self.batch, "breed_name", "").strip())
        confidence = "medium" if breed_known else "low"

        return {
            "estimated_value_naira": _money(total),
            "valuation_method": "point_of_lay",
            "price_per_unit": _money(price_per_bird),
            "unit": "bird",
            "current_count": count,
            "as_of": timezone.now(),
            "confidence": confidence,
            "price_source": "fallback",
            "is_laying": is_laying,
            "notes": notes,
        }

    # ── Unknown / other ─────────────────────────────────────────────────────────

    def _fallback_estimate(self) -> dict:
        """Unknown/other bird types — flat per-bird estimate, low confidence."""
        count = self.batch.current_count or 0
        price_per_bird = FALLBACK_PER_BIRD
        total = Decimal(count) * price_per_bird
        return {
            "estimated_value_naira": _money(total),
            "valuation_method": "fallback_per_bird",
            "price_per_unit": _money(price_per_bird),
            "unit": "bird",
            "current_count": count,
            "as_of": timezone.now(),
            "confidence": "low",
            "price_source": "fallback",
            "notes": "Generic per-bird estimate — bird type not recognised.",
        }
