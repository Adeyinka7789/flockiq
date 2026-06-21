"""
Breed performance benchmarks for FlockIQ analytics.

Nigerian/West African poultry breed benchmarks.
Sources: Cobb-Vantress, Ross (Aviagen), Hy-Line International, ISA,
NAERLS Nigeria poultry production guidelines.
All values are typical performance targets.

ARCHITECTURE NOTE:
These benchmarks are intentionally hardcoded for now. They are based on
published breed standards (Cobb 500, Ross 308, Aviagen, Hy-Line, ISA) and
empirical Nigerian farm data.

DO NOT move to DB until there is real user demand for breed-specific tuning.
The access pattern already funnels through get_benchmark() and BREED_ALIASES —
a DB migration is clean when needed (see CLAUDE.md: Breed Benchmarks).

ValuationSettings (apps/infrastructure/billing/models.py) is PRICING ONLY — it
is not related to these benchmarks.

A future BreedBenchmark model should:
- Follow the BillingPlan/ValuationSettings pattern (global, RLS-disabled,
  seeded via data migration)
- Include a nullable country/region field from day one
- Expose a superadmin CRUD view for non-technical updates
- Keep the BREED_BENCHMARKS dict here as an emergency fallback if the DB is
  unavailable
"""

BREED_BENCHMARKS = {
    # ── BROILERS ──────────────────────────────────────────────
    'cobb_500': {
        'name': 'Cobb 500',
        'type': 'broiler',
        'target_fcr': 1.65,
        'target_mortality_rate_pct': 3.5,
        'target_weight_day38_kg': 2.1,
        'target_weight_day42_kg': 2.4,
        'target_weight_day45_kg': 2.65,
        'optimal_slaughter_day': 42,
        'water_per_bird_ml': 250,
        'feed_per_bird_day_g': 110,
        'daily_weight_gain_g': 58,
    },
    'ross_308': {
        'name': 'Ross 308',
        'type': 'broiler',
        'target_fcr': 1.60,
        'target_mortality_rate_pct': 3.0,
        'target_weight_day38_kg': 2.2,
        'target_weight_day42_kg': 2.5,
        'target_weight_day45_kg': 2.75,
        'optimal_slaughter_day': 40,
        'water_per_bird_ml': 260,
        'feed_per_bird_day_g': 115,
        'daily_weight_gain_g': 62,
    },
    'arbor_acres': {
        'name': 'Arbor Acres',
        'type': 'broiler',
        'target_fcr': 1.70,
        'target_mortality_rate_pct': 4.0,
        'target_weight_day38_kg': 2.0,
        'target_weight_day42_kg': 2.3,
        'target_weight_day45_kg': 2.55,
        'optimal_slaughter_day': 42,
        'water_per_bird_ml': 245,
        'feed_per_bird_day_g': 108,
        'daily_weight_gain_g': 55,
    },
    'noiler': {
        'name': 'Noiler',
        'type': 'broiler',
        'target_fcr': 2.20,
        'target_mortality_rate_pct': 5.0,
        'target_weight_day38_kg': 1.4,
        'target_weight_day42_kg': 1.6,
        'target_weight_day45_kg': 1.8,
        'optimal_slaughter_day': 56,
        'water_per_bird_ml': 200,
        'feed_per_bird_day_g': 85,
        'daily_weight_gain_g': 35,
    },

    # ── LAYERS ────────────────────────────────────────────────
    'hyline_brown': {
        'name': 'Hy-Line Brown',
        'type': 'layer',
        'target_hen_day_pct': 92.0,
        'target_peak_production_pct': 95.0,
        'target_mortality_rate_pct': 5.0,
        'eggs_per_hen_72_weeks': 340,
        'feed_per_bird_day_g': 115,
        'water_per_bird_ml': 230,
        'optimal_lay_start_week': 18,
    },
    'isa_brown': {
        'name': 'ISA Brown',
        'type': 'layer',
        'target_hen_day_pct': 93.0,
        'target_peak_production_pct': 96.0,
        'target_mortality_rate_pct': 4.5,
        'eggs_per_hen_72_weeks': 355,
        'feed_per_bird_day_g': 112,
        'water_per_bird_ml': 225,
        'optimal_lay_start_week': 17,
    },

    # ── DEFAULT FALLBACK ──────────────────────────────────────
    'default_broiler': {
        'name': 'Standard Broiler',
        'type': 'broiler',
        'target_fcr': 1.80,
        'target_mortality_rate_pct': 4.0,
        'target_weight_day42_kg': 2.2,
        'optimal_slaughter_day': 42,
        'water_per_bird_ml': 240,
        'feed_per_bird_day_g': 105,
        'daily_weight_gain_g': 50,
    },
    'default_layer': {
        'name': 'Standard Layer',
        'type': 'layer',
        'target_hen_day_pct': 88.0,
        'target_peak_production_pct': 92.0,
        'target_mortality_rate_pct': 5.5,
        'feed_per_bird_day_g': 110,
        'water_per_bird_ml': 220,
    },
}

BREED_ALIASES = {
    'cobb': 'cobb_500',
    'cobb500': 'cobb_500',
    'cobb 500': 'cobb_500',
    'ross': 'ross_308',
    'ross308': 'ross_308',
    'ross 308': 'ross_308',
    'arbor': 'arbor_acres',
    'aa': 'arbor_acres',
    'noiler': 'noiler',
    'hy-line': 'hyline_brown',
    'hyline': 'hyline_brown',
    'hy line': 'hyline_brown',
    'isa': 'isa_brown',
    'isa brown': 'isa_brown',
}


def get_benchmark(breed_name: str, bird_type: str = 'broiler') -> dict:
    """Return benchmark dict for a breed name. Falls back to default_broiler or default_layer."""
    if not breed_name:
        key = f'default_{bird_type}'
        return BREED_BENCHMARKS.get(key, BREED_BENCHMARKS['default_broiler'])

    normalized = breed_name.lower().strip()

    if normalized in BREED_BENCHMARKS:
        return BREED_BENCHMARKS[normalized]

    alias_key = BREED_ALIASES.get(normalized)
    if alias_key:
        return BREED_BENCHMARKS[alias_key]

    for alias, key in BREED_ALIASES.items():
        if alias in normalized or normalized in alias:
            return BREED_BENCHMARKS[key]

    fallback = f'default_{bird_type}'
    return BREED_BENCHMARKS.get(fallback, BREED_BENCHMARKS['default_broiler'])


def compare_batch_to_benchmark(batch, fcr=None, mortality_rate=None, hen_day_pct=None) -> dict:
    """Compare batch metrics to breed benchmark. Returns dict of comparisons with status flags."""
    benchmark = get_benchmark(
        getattr(batch, 'breed_name', None),
        getattr(batch, 'bird_type', 'broiler'),
    )
    result = {
        'benchmark': benchmark,
        'breed_name': benchmark['name'],
        'comparisons': [],
    }

    if fcr and 'target_fcr' in benchmark:
        target = benchmark['target_fcr']
        diff = fcr - target
        pct_diff = round(diff / target * 100, 1)
        status = ('good' if diff <= 0
                  else 'warning' if pct_diff <= 10
                  else 'critical')
        result['comparisons'].append({
            'metric': 'FCR',
            'actual': fcr,
            'target': target,
            'diff': round(diff, 2),
            'pct_diff': pct_diff,
            'status': status,
            'message': (
                f'FCR {fcr} is '
                f'{"within" if status == "good" else "above"} '
                f'{benchmark["name"]} target of {target}'
            ),
        })

    if mortality_rate is not None and 'target_mortality_rate_pct' in benchmark:
        target = benchmark['target_mortality_rate_pct']
        diff = mortality_rate - target
        status = ('good' if diff <= 0
                  else 'warning' if diff <= 1.5
                  else 'critical')
        result['comparisons'].append({
            'metric': 'Mortality Rate',
            'actual': round(mortality_rate, 2),
            'target': target,
            'diff': round(diff, 2),
            'status': status,
            'message': (
                f'Mortality {mortality_rate:.1f}% vs '
                f'{benchmark["name"]} target {target}%'
            ),
        })

    if hen_day_pct and 'target_hen_day_pct' in benchmark:
        target = benchmark['target_hen_day_pct']
        diff = hen_day_pct - target
        status = ('good' if diff >= 0
                  else 'warning' if diff >= -5
                  else 'critical')
        result['comparisons'].append({
            'metric': 'Hen-Day %',
            'actual': round(hen_day_pct, 1),
            'target': target,
            'diff': round(diff, 1),
            'status': status,
            'message': (
                f'Hen-day {hen_day_pct:.1f}% vs '
                f'{benchmark["name"]} target {target}%'
            ),
        })

    return result
