from datetime import date, timedelta

NIGERIAN_SEASONAL_EVENTS = [
    {
        "name": "Ramadan / Eid",
        "typical_months": [3, 4],
        "egg_demand_multiplier": 1.2,
        "broiler_demand_multiplier": 1.6,
        "note": "Broiler demand surges for Sallah celebrations",
        "advice": "Place broiler batches 6 weeks before Ramadan ends",
    },
    {
        "name": "Christmas & New Year",
        "typical_months": [12],
        "egg_demand_multiplier": 1.4,
        "broiler_demand_multiplier": 2.0,
        "note": "Highest demand period of the year",
        "advice": "Place batches in mid-October for Christmas readiness",
    },
    {
        "name": "Easter",
        "typical_months": [3, 4],
        "egg_demand_multiplier": 1.5,
        "broiler_demand_multiplier": 1.3,
        "note": "Egg demand peaks significantly at Easter",
        "advice": "Maximize layer flock size heading into March/April",
    },
    {
        "name": "Back to School",
        "typical_months": [1, 9],
        "egg_demand_multiplier": 1.15,
        "broiler_demand_multiplier": 1.1,
        "note": "Modest demand uptick as families restock",
        "advice": "Good time for smaller batch placements",
    },
    {
        "name": "Ember Months (Oct–Dec)",
        "typical_months": [10, 11, 12],
        "egg_demand_multiplier": 1.3,
        "broiler_demand_multiplier": 1.5,
        "note": "Generally elevated demand across all ember months",
        "advice": "Maximize flock size during October–December",
    },
]


class SeasonalAdvisor:
    """Provides Nigerian seasonal demand insights for farmers."""

    def get_current_season_insight(self) -> dict:
        current_month = date.today().month
        next_month = (current_month % 12) + 1

        current_events = [
            e for e in NIGERIAN_SEASONAL_EVENTS if current_month in e["typical_months"]
        ]
        upcoming_events = [
            e for e in NIGERIAN_SEASONAL_EVENTS if next_month in e["typical_months"]
        ]

        return {
            "current_events": current_events,
            "upcoming_events": upcoming_events,
            "month": date.today().strftime("%B"),
        }

    def get_placement_recommendation(self) -> str:
        """
        Should you place a broiler batch this week?
        Returns advice based on demand 6 weeks from now.
        """
        market_month = (date.today() + timedelta(weeks=6)).month

        for event in NIGERIAN_SEASONAL_EVENTS:
            if market_month in event["typical_months"]:
                multiplier = event["broiler_demand_multiplier"]
                if multiplier >= 1.5:
                    return (
                        f"Good time to place — {event['name']} in ~6 weeks "
                        f"(demand +{int((multiplier - 1) * 100)}%). "
                        f"{event['advice']}"
                    )
        return "Normal demand period expected at market time."
