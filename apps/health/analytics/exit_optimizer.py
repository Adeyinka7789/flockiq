class BroilerExitOptimizer:
    """
    Calculates optimal sell date for broiler batches.
    Shows daily cost of holding vs expected gain.
    Pure Python — no ORM access.
    """

    # Cobb 500 daily weight gain by age (grams)
    DAILY_GAIN_TABLE = [
        (range(1, 8), 18),
        (range(8, 15), 35),
        (range(15, 22), 55),
        (range(22, 29), 65),
        (range(29, 36), 58),
        (range(36, 43), 45),
        (range(43, 50), 30),
        (range(50, 60), 18),
    ]

    def get_daily_gain(self, day: int) -> int:
        for day_range, gain in self.DAILY_GAIN_TABLE:
            if day in day_range:
                return gain
        return 10

    def analyze(self, batch, price_per_kg_naira: int = 1850) -> dict:
        """
        Returns exit analysis for a broiler batch.
        """
        day = batch.cycle_day
        bird_count = batch.current_count

        # Cumulative weight from day 1
        estimated_weight_g = sum(self.get_daily_gain(d) for d in range(1, day + 1))

        # Daily feed cost estimate
        feed_per_bird_g = min(130, 60 + day * 2)
        feed_cost_per_kg = 500  # ₦500/kg feed estimate
        daily_feed_cost = bird_count * feed_per_bird_g / 1000 * feed_cost_per_kg

        # Daily weight gain value
        daily_gain_g = self.get_daily_gain(day)
        daily_gain_value = bird_count * daily_gain_g / 1000 * price_per_kg_naira

        # Optimal window: day 35–42
        if day < 35:
            recommendation = "wait"
            days_until = 35 - day
            message = f"Optimal window in {days_until} days (Day 35)"
        elif day <= 42:
            recommendation = "sell_now"
            days_until = 0
            message = "You are in the optimal sale window"
        else:
            recommendation = "urgent"
            days_until = 0
            message = f"Past optimal window by {day - 42} days"

        est_weight_kg = bird_count * estimated_weight_g / 1000
        est_revenue = est_weight_kg * price_per_kg_naira
        net_daily = daily_gain_value - daily_feed_cost

        return {
            "day": day,
            "estimated_weight_g": round(estimated_weight_g),
            "est_weight_kg": round(est_weight_kg, 1),
            "est_revenue": round(est_revenue),
            "daily_feed_cost": round(daily_feed_cost),
            "daily_gain_value": round(daily_gain_value),
            "net_daily_value": round(net_daily),
            "recommendation": recommendation,
            "days_until_optimal": days_until,
            "message": message,
            "price_per_kg": price_per_kg_naira,
        }
