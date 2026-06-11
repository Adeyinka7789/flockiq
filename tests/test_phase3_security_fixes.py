"""
Phase 3 security-audit fixes — medium severity correctness and hardening.

Covers:
  Bug 11 — expiry/trial reminder day math is calendar-date based, so an org
           activated at 07:00 checked at 08:00 still gets its 7-day reminder;
           mark_lapsed_orgs compares dates, not datetimes
  Bug 12 — credit score FCR uses surviving bird count (current_count), not
           initial_count, so high-mortality batches stop looking efficient
  Bug 14 — signup is rate limited, normalises email to lowercase, blocks an
           expanded reserved-subdomain list, and survives the subdomain
           uniqueness race via IntegrityError handling
  Bug 16 — assert_tenant_context raises in DEBUG and alerts Sentry otherwise
  Bug 17 — fan-out beat tasks dispatch per-org subtasks instead of iterating
           every org inside one task
"""

import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone

from apps.infrastructure.core.rls import set_tenant_context

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_org(**kwargs):
    from apps.infrastructure.tenants.models import Organization
    subdomain = f"p3audit-{uuid.uuid4().hex[:8]}"
    defaults = {
        "name": "Phase3 Farm",
        "subdomain": subdomain,
        "owner_email": f"{subdomain}@test.com",
        "plan_tier": "monthly",
        "subscription_status": "active",
        "is_active": True,
    }
    defaults.update(kwargs)
    return Organization.objects.create(**defaults)


@pytest.fixture(autouse=True)
def _clear_cache():
    """Throttle counters live in the cache — isolate every test."""
    cache.clear()
    yield
    cache.clear()


def signup_data(**overrides):
    data = {
        "org_name": "New Farm",
        "owner_name": "Ada Obi",
        "email": f"ada-{uuid.uuid4().hex[:8]}@example.com",
        "phone": "08012345678",
        "subdomain": f"newfarm-{uuid.uuid4().hex[:8]}",
        "country": "NG",
        "state_region": "Lagos",
        "password": "s3curePass!",
        "confirm_password": "s3curePass!",
    }
    data.update(overrides)
    return data


# ---------------------------------------------------------------------------
# Bug 11 — reminder day math is date-based, not timedelta-truncated
# ---------------------------------------------------------------------------

class TestReminderDayMath:
    def test_expiry_reminder_fires_on_exact_day_despite_time_of_day(self):
        # Expires 7 calendar days from today, but at 00:01 — earlier in the
        # day than the beat run, so (expiry - now).days truncates to 6 and the
        # old code never sent the 7-day reminder.
        expiry = timezone.now().replace(
            hour=0, minute=1, second=0, microsecond=0
        ) + timedelta(days=7)
        org = make_org(plan_expires_at=expiry)

        from apps.infrastructure.billing import tasks
        with patch.object(tasks.send_expiry_reminder_for_org, "delay") as mock_delay:
            tasks.send_subscription_expiry_reminders()

        dispatched = {call.args for call in mock_delay.call_args_list}
        assert (str(org.id), 7) in dispatched

    def test_expiry_reminder_skips_non_reminder_days(self):
        org = make_org(plan_expires_at=timezone.now() + timedelta(days=5))

        from apps.infrastructure.billing import tasks
        with patch.object(tasks.send_expiry_reminder_for_org, "delay") as mock_delay:
            tasks.send_subscription_expiry_reminders()

        dispatched_org_ids = {call.args[0] for call in mock_delay.call_args_list}
        assert str(org.id) not in dispatched_org_ids

    def test_trial_reminder_fires_on_exact_day_despite_time_of_day(self):
        trial_end = timezone.now().replace(
            hour=0, minute=1, second=0, microsecond=0
        ) + timedelta(days=3)
        org = make_org(
            plan_tier="trial",
            subscription_status="trial",
            trial_ends_at=trial_end,
        )

        from apps.infrastructure.billing import tasks
        with patch.object(tasks.send_trial_reminder_for_org, "delay") as mock_delay:
            tasks.send_trial_expiry_reminders()

        dispatched = {call.args for call in mock_delay.call_args_list}
        assert (str(org.id), 3) in dispatched

    def test_mark_lapsed_uses_date_comparison(self):
        from apps.infrastructure.billing.tasks import mark_lapsed_orgs

        expired_yesterday = make_org(
            plan_expires_at=timezone.now() - timedelta(days=2),
        )
        # Expires later today — date is not strictly before today, so the org
        # must NOT be flagged until tomorrow's run.
        expires_today = make_org(
            plan_expires_at=timezone.now().replace(
                hour=23, minute=59, second=0, microsecond=0
            ),
        )

        mark_lapsed_orgs()

        expired_yesterday.refresh_from_db()
        expires_today.refresh_from_db()
        assert expired_yesterday.subscription_status == "lapsed"
        assert expires_today.subscription_status == "active"


# ---------------------------------------------------------------------------
# Bug 12 — credit score FCR uses surviving bird count
# ---------------------------------------------------------------------------

class TestCreditScoreFCRUsesCurrentCount:
    def _make_closed_batch_with_logs(self, org, farm, house, current_count):
        from datetime import date

        from apps.farm.flocks.models import Batch, WeightRecord
        from apps.production.feed.models import FeedLog

        with set_tenant_context(org):
            batch = Batch.objects.create(
                org=org,
                farm=farm,
                house=house,
                batch_name=f"Broilers-{uuid.uuid4().hex[:6]}",
                bird_type="broiler",
                placement_date=date.today() - timedelta(days=42),
                initial_count=1000,
                current_count=1000,
                status="active",
            )
            FeedLog.objects.create(
                org=org,
                batch=batch,
                farm=farm,
                record_date=date.today(),
                quantity_kg=3600,
            )
            WeightRecord.objects.create(
                org=org,
                batch=batch,
                sample_date=date.today(),
                sample_size=50,
                avg_weight_kg=2,
            )
            batch.current_count = current_count
            batch.status = "closed"
            batch.closed_at = timezone.now()
            batch.save()
        return batch

    def test_fcr_scored_on_surviving_birds(self, test_org, test_farm, test_house):
        from apps.infrastructure.core.credit_scoring import CreditScoringService

        # 3600 kg feed, 2 kg avg weight: with the old initial_count maths the
        # FCR is 3600 / (2 x 1000) = 1.8 (score 100). With 20% mortality the
        # honest FCR is 3600 / (2 x 800) = 2.25 (score 40).
        batch = self._make_closed_batch_with_logs(
            test_org, test_farm, test_house, current_count=800
        )

        with set_tenant_context(test_org):
            score = CreditScoringService(test_org)._score_feed_efficiency([batch])

        assert score == 40

    def test_fcr_neutral_when_no_survivors(self, test_org, test_farm, test_house):
        from apps.infrastructure.core.credit_scoring import CreditScoringService

        batch = self._make_closed_batch_with_logs(
            test_org, test_farm, test_house, current_count=0
        )

        with set_tenant_context(test_org):
            score = CreditScoringService(test_org)._score_feed_efficiency([batch])

        assert score == 50


# ---------------------------------------------------------------------------
# Bug 14 — signup hardening
# ---------------------------------------------------------------------------

class TestSignupThrottle:
    def test_signup_rate_limited_after_threshold(self, client):
        # DEFAULT_THROTTLE_RATES["signup"] is 5/hour — the 6th POST gets 429.
        for _ in range(5):
            response = client.post("/signup/", {})
            assert response.status_code == 200

        response = client.post("/signup/", {})
        assert response.status_code == 429

    def test_get_is_not_throttled(self, client):
        for _ in range(6):
            response = client.get("/signup/")
            assert response.status_code == 200


class TestSignupReservedSubdomains:
    @pytest.mark.parametrize("subdomain", ["admin", "billing", "support"])
    def test_reserved_subdomain_rejected(self, client, subdomain):
        response = client.post("/signup/", signup_data(subdomain=subdomain))
        assert response.status_code == 200
        assert b"This subdomain is reserved" in response.content

    def test_reserved_list_contains_expanded_entries(self):
        from apps.infrastructure.accounts.views import RESERVED_SUBDOMAINS

        assert {"admin", "billing", "support", "superadmin", "smtp", "staging"} \
            <= RESERVED_SUBDOMAINS


class TestSignupEmailNormalisation:
    def test_email_lowercased_on_signup(self, client):
        from apps.infrastructure.accounts.models import CustomUser

        with patch(
            "apps.infrastructure.accounts.views.EmailService.send_verification"
        ):
            response = client.post(
                "/signup/",
                signup_data(email="Mixed.Case@Example.COM"),
            )

        assert response.status_code == 302
        user = CustomUser.objects.get(email="mixed.case@example.com")
        assert user.org.owner_email == "mixed.case@example.com"

    def test_duplicate_email_check_case_insensitive(self, client, tenant_user):
        response = client.post(
            "/signup/",
            signup_data(email=tenant_user.email.upper()),
        )
        assert response.status_code == 200
        assert b"An account with this email already exists" in response.content


class TestSignupSubdomainRace:
    def test_integrity_error_returns_form_error_not_500(self, client):
        from django.db import IntegrityError

        from apps.infrastructure.tenants.models import Organization

        # Simulate the race: the advisory exists() check passed (another
        # request claimed the subdomain between check and insert), so the
        # unique constraint fires on create.
        with patch.object(
            Organization.objects, "create", side_effect=IntegrityError
        ):
            response = client.post("/signup/", signup_data())

        assert response.status_code == 200
        assert b"already taken" in response.content


# ---------------------------------------------------------------------------
# Bug 16 — assert_tenant_context fails loudly
# ---------------------------------------------------------------------------

class TestAssertTenantContext:
    def test_raises_in_debug_when_context_missing(self):
        from django.db import connection

        from apps.infrastructure.core.rls import assert_tenant_context

        if "sqlite" in connection.vendor:
            pytest.skip("RLS context assertions are skipped on SQLite")

        with override_settings(DEBUG=True):
            with pytest.raises(RuntimeError, match="set_tenant_context"):
                assert_tenant_context()

    def test_alerts_sentry_without_raising_in_production(self):
        from django.db import connection

        from apps.infrastructure.core.rls import assert_tenant_context

        if "sqlite" in connection.vendor:
            pytest.skip("RLS context assertions are skipped on SQLite")

        with override_settings(DEBUG=False):
            with patch("sentry_sdk.capture_message") as mock_capture:
                assert_tenant_context()  # must not raise

        mock_capture.assert_called_once()

    def test_passes_silently_inside_tenant_context(self, test_org):
        from django.db import connection

        from apps.infrastructure.core.rls import assert_tenant_context

        if "sqlite" in connection.vendor:
            pytest.skip("RLS context assertions are skipped on SQLite")

        with set_tenant_context(test_org):
            with patch("sentry_sdk.capture_message") as mock_capture:
                assert_tenant_context()

        mock_capture.assert_not_called()


# ---------------------------------------------------------------------------
# Bug 17 — fan-out beat tasks dispatch per-org subtasks
# ---------------------------------------------------------------------------

class TestFanOutTasks:
    def test_monthly_billing_dispatches_per_org_subtasks(self):
        from apps.infrastructure.billing import tasks

        org_a = make_org()
        org_b = make_org(plan_tier="yearly")
        inactive = make_org(is_active=False)

        with patch.object(tasks.process_billing_for_org, "delay") as mock_delay:
            tasks.process_monthly_billing_cycle()

        dispatched = {call.args[0] for call in mock_delay.call_args_list}
        assert str(org_a.id) in dispatched
        assert str(org_b.id) in dispatched
        assert str(inactive.id) not in dispatched

    def test_per_org_billing_task_ignores_deleted_org(self):
        from apps.infrastructure.billing.tasks import process_billing_for_org

        # Must return cleanly, not raise or retry.
        process_billing_for_org(str(uuid.uuid4()))

    def test_expiry_reminder_parent_does_not_send_inline(self):
        """The parent task must only dispatch — never touch EmailService."""
        org = make_org(
            plan_expires_at=timezone.now().replace(
                hour=0, minute=1, second=0, microsecond=0
            ) + timedelta(days=1),
        )

        from apps.infrastructure.billing import tasks
        with patch.object(tasks.send_expiry_reminder_for_org, "delay") as mock_delay, \
                patch("apps.infrastructure.core.email_service.EmailService") as mock_email:
            tasks.send_subscription_expiry_reminders()

        assert (str(org.id), 1) in {call.args for call in mock_delay.call_args_list}
        mock_email.send_expiry_reminder.assert_not_called()
