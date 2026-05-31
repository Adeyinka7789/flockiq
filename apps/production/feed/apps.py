from django.apps import AppConfig


class FeedConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.production.feed"
    label = "feed"

    def ready(self):
        import apps.production.feed.signals  # noqa: F401
