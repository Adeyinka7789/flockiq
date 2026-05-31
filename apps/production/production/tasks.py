from celery import shared_task


@shared_task(name="production.run_egg_forecast")
def run_egg_forecast(org_id: str, batch_id: str):
    """Phase 4 stub — ProphetForecastService will be wired here."""
    pass
