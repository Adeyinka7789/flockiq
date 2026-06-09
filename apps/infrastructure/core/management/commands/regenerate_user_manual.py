from django.core.cache import cache
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Invalidate the cached user manual PDF"

    def handle(self, *args, **options):
        cache.delete("flockiq_user_manual_pdf_v1")
        self.stdout.write(
            self.style.SUCCESS(
                "User manual cache cleared. Will regenerate on next request."
            )
        )
