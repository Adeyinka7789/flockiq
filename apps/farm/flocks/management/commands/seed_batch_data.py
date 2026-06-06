# CORRECTED: apps/farm/flocks/management/commands/seed_batch_data.py
# Improvements: Direct org lookup, uses select_related(), better error handling

from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db.models import Sum
from datetime import date, timedelta
import random
import structlog

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = 'Seeds realistic backdated data for a batch (dev only)'

    def add_arguments(self, parser):
        parser.add_argument('--batch', type=str,
                            help='Batch UUID (optional, uses first active batch)')
        parser.add_argument('--org', type=str,
                            help='Organization UUID (optional, searches all if not provided)')
        parser.add_argument('--days', type=int, default=30,
                            help='Days of history to generate (default: 30)')

    def handle(self, *args, **kwargs):
        from apps.infrastructure.tenants.models import Organization
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.farm.flocks.models import Batch, MortalityLog
        from apps.production.production.models import EggProductionLog
        from apps.production.feed.models import FeedLog
        from apps.production.water.models import WaterLog

        random.seed(42)
        days = kwargs['days']
        batch_id = kwargs.get('batch')
        org_id = kwargs.get('org')

        # ── Resolve org + batch ────────────────────────────────────────
        org = None
        batch = None

        if org_id:
            # Direct lookup if org specified
            try:
                org = Organization.objects.get(id=org_id, is_active=True)
            except Organization.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'Organization {org_id} not found or inactive.'))
                return
        else:
            org = Organization.objects.filter(is_active=True).first()
            if not org:
                self.stdout.write(self.style.ERROR('No active org found.'))
                return

        if batch_id:
            with set_tenant_context(org):
                batch = Batch.objects.filter(pk=batch_id).select_related('farm', 'house').first()
                if not batch:
                    self.stdout.write(self.style.ERROR(f'Batch {batch_id} not found in org {org.subdomain}.'))
                    return
        else:
            with set_tenant_context(org):
                batch = Batch.objects.filter(status='active').select_related('farm', 'house').first()
                if not batch:
                    self.stdout.write(self.style.ERROR('No active batch found in org.'))
                    return


        # ── Backdate placement if needed ────────────────────────────────
        with set_tenant_context(org):
            today = date.today()

            # If the batch was placed too recently there is nothing to backfill.
            # Backdate placement_date so the seeding window fits.
            min_placement = today - timedelta(days=days + 7)
            if batch.placement_date > min_placement:
                try:
                    Batch.objects.filter(pk=batch.pk).update(
                        placement_date=min_placement)
                    batch.placement_date = min_placement
                    self.stdout.write(
                        self.style.WARNING(
                            f'  placement_date backdated to {min_placement} '
                            f'to fit {days}-day seed window.'
                        )
                    )
                except Exception as exc:
                    self.stdout.write(self.style.ERROR(f'Error updating placement_date: {str(exc)}'))
                    logger.exception("seed_batch_data.placement_update_failed", batch_id=str(batch.pk))
                    return

            self.stdout.write(f'Seeding data for: {batch.batch_name} '
                              f'({batch.bird_type}) - {days} days')
            
            created_mortality = 0
            created_eggs = 0
            created_feed = 0
            created_water = 0

            for i in range(days, 0, -1):
                day = today - timedelta(days=i)
                day_of_batch = (day - batch.placement_date).days
                if day_of_batch < 1:
                    continue

                # ── MORTALITY ──────────────────────────────────────────
                mortality_count = 0
                cause = 'unknown'
                
                if day_of_batch in [19, 20]:
                    mortality_count = random.randint(10, 15)
                    cause = 'disease'
                elif day_of_batch % 7 == 0:
                    mortality_count = random.randint(2, 4)
                    cause = 'unknown'
                else:
                    mortality_count = random.randint(0, 2)
                    cause = random.choice(['disease', 'accident', 'unknown', 'culling'])

                if mortality_count > 0:
                    try:
                        if not MortalityLog.objects.filter(batch=batch, date=day).exists():
                            MortalityLog.objects.create(
                                org=org,
                                batch=batch,
                                farm=batch.farm,
                                date=day,
                                count=mortality_count,
                                cause=cause,
                            )
                            created_mortality += 1
                    except Exception as exc:
                        logger.warning("seed_batch_data.mortality_creation_failed", batch_id=str(batch.pk), day=str(day), error=str(exc))

                # ── EGG PRODUCTION (layers only) ───────────────────────
                if batch.bird_type == 'layer' and day_of_batch >= 18:
                    base_pct = min(88, 40 + day_of_batch * 1.5)
                    hen_day_pct = round(max(30, base_pct + random.uniform(-5, 5)), 1)

                    live_birds = batch.current_count
                    total_eggs = int(live_birds * hen_day_pct / 100)
                    grade_a = int(total_eggs * random.uniform(0.88, 0.94))
                    grade_b = min(
                        int(total_eggs * random.uniform(0.04, 0.08)),
                        max(0, total_eggs - grade_a),
                    )
                    cracked = max(0, total_eggs - grade_a - grade_b)

                    try:
                        if not EggProductionLog.objects.filter(
                                batch=batch, record_date=day).exists():
                            EggProductionLog.objects.create(
                                org=org,
                                batch=batch,
                                farm=batch.farm,
                                house=batch.house,
                                record_date=day,
                                total_eggs=total_eggs,
                                grade_a=grade_a,
                                grade_b=grade_b,
                                cracked=cracked,
                                hen_day_pct=Decimal(str(hen_day_pct)),
                            )
                            created_eggs += 1
                    except Exception as exc:
                        logger.warning("seed_batch_data.egg_creation_failed", batch_id=str(batch.pk), day=str(day), error=str(exc))

                # ── FEED LOG ───────────────────────────────────────────
                live_birds = batch.current_count
                kg_per_bird = min(0.13, 0.05 + day_of_batch * 0.002)
                actual_feed_kg = Decimal(str(
                    round(live_birds * kg_per_bird * random.uniform(0.95, 1.05), 2)
                ))

                try:
                    if not FeedLog.objects.filter(batch=batch, record_date=day).exists():
                        feed_type = (
                            'starter' if day_of_batch < 14
                            else 'grower' if day_of_batch < 28
                            else 'layer_mash' if batch.bird_type == 'layer'
                            else 'finisher'
                        )
                        FeedLog.objects.create(
                            org=org,
                            batch=batch,
                            farm=batch.farm,
                            record_date=day,
                            quantity_kg=actual_feed_kg,
                            feed_type=feed_type,
                        )
                        created_feed += 1
                except Exception as exc:
                    logger.warning("seed_batch_data.feed_creation_failed", batch_id=str(batch.pk), day=str(day), error=str(exc))

                # ── WATER LOG ──────────────────────────────────────────
                base_water_l = live_birds * Decimal('0.25')
                # Stress-drop anomaly on day 22
                if day_of_batch == 22:
                    actual_water_l = round(base_water_l * Decimal('0.55'), 2)
                else:
                    actual_water_l = round(
                        base_water_l * Decimal(str(random.uniform(0.9, 1.1))), 2)

                try:
                    if not WaterLog.objects.filter(batch=batch, record_date=day).exists():
                        WaterLog.objects.create(
                            org=org,
                            batch=batch,
                            farm=batch.farm,
                            record_date=day,
                            litres_consumed=actual_water_l,
                        )
                        created_water += 1
                except Exception as exc:
                    logger.warning("seed_batch_data.water_creation_failed", batch_id=str(batch.pk), day=str(day), error=str(exc))

            # ── UPDATE current_count ───────────────────────────────────
            try:
                total_mortality = (
                    MortalityLog.objects.filter(batch=batch)
                    .aggregate(total=Sum('count'))['total'] or 0
                )
                new_count = max(0, batch.initial_count - total_mortality)
                if new_count != batch.current_count:
                    Batch.objects.filter(pk=batch.pk).update(current_count=new_count)
                    self.stdout.write(
                        f'  Updated current_count: {batch.initial_count} -> {new_count}')
            except Exception as exc:
                logger.exception("seed_batch_data.count_update_failed", batch_id=str(batch.pk))
                self.stdout.write(self.style.ERROR(f'Error updating current_count: {str(exc)}'))

        self.stdout.write(self.style.SUCCESS(
            f'\nDone! Created:\n'
            f'  Mortality logs:      {created_mortality}\n'
            f'  Egg production logs: {created_eggs}\n'
            f'  Feed logs:           {created_feed}\n'
            f'  Water logs:          {created_water}\n'
            f'\nRun: python manage.py runserver\n'
            f'Then visit your batch AI Insights tab.'
        ))
