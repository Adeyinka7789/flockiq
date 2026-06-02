from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Seeds default FlockIQ billing plans"

    def handle(self, *args, **kwargs):
        from apps.infrastructure.billing.models import BillingPlan

        plans = [
            {
                "name": "Free Trial",
                "plan_tier": "trial",
                "amount_kobo": 0,
                "billing_interval": "monthly",
                "features": [
                    "1 farm, 1 active batch",
                    "All daily logging features",
                    "Basic dashboard",
                    "14-day full access",
                ],
            },
            {
                "name": "Monthly",
                "plan_tier": "monthly",
                "amount_kobo": 3000000,
                "billing_interval": "monthly",
                "features": [
                    "Up to 3 farms",
                    "All features + AI alerts",
                    "SMS notifications",
                    "PDF & Excel exports",
                    "Weather intelligence",
                ],
            },
            {
                "name": "Cycle",
                "plan_tier": "cycle",
                "amount_kobo": 1500000,
                "billing_interval": "per_cycle",
                "features": [
                    "Per 6-week broiler cycle",
                    "Activates on batch placement",
                    "All features included",
                ],
            },
            {
                "name": "Yearly",
                "plan_tier": "yearly",
                "amount_kobo": 30000000,
                "billing_interval": "annually",
                "features": [
                    "Unlimited farms",
                    "Advanced AI features",
                    "White-label option",
                    "Priority support",
                    "2 months free",
                ],
            },
        ]

        for p in plans:
            obj, created = BillingPlan.objects.get_or_create(
                plan_tier=p["plan_tier"],
                defaults={
                    "name": p["name"],
                    "amount_kobo": p["amount_kobo"],
                    "billing_interval": p["billing_interval"],
                    "features": p["features"],
                    "is_active": True,
                },
            )
            status = "Created" if created else "Exists"
            self.stdout.write(f"{status}: {obj.name}")

        self.stdout.write(self.style.SUCCESS("Done."))
