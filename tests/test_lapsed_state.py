"""
Lapsed-subscription state tests.

Covers:
  - Organization.is_lapsed property
  - billing.features.can_write_data gate
  - write views return 402 for lapsed orgs (read stays allowed)
  - activate_plan clears the lapsed state
  - billing page button states (no downgrade buttons, trial one-time only)
"""
import uuid
from datetime import date, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_org(subdomain=None, **kwargs):
    from apps.infrastructure.tenants.models import Organization
    subdomain = subdomain or f"lapsed-{uuid.uuid4().hex[:8]}"
    defaults = {
        "name": "Lapsed Farm",
        "subdomain": subdomain,
        "owner_email": f"{subdomain}@test.com",
        "plan_tier": "monthly",
        "subscription_status": "active",
        "is_active": True,
    }
    defaults.update(kwargs)
    return Organization.objects.create(**defaults)


def make_plan(plan_tier, amount_kobo, interval="monthly"):
    from apps.infrastructure.billing.models import BillingPlan
    return BillingPlan.objects.create(
        name=f"{plan_tier.title()} Plan",
        plan_tier=plan_tier,
        paystack_plan_code=f"PLN_{plan_tier}_{uuid.uuid4().hex[:6]}",
        amount_kobo=amount_kobo,
        billing_interval=interval,
        is_active=True,
    )


# ---------------------------------------------------------------------------
# Organization.is_lapsed
# ---------------------------------------------------------------------------

class TestIsLapsedProperty:
    def test_lapsed_true_when_expiry_passed_and_not_active(self):
        org = make_org(
            plan_tier="monthly",
            subscription_status="past_due",
            plan_expires_at=timezone.now() - timedelta(days=2),
        )
        assert org.is_lapsed is True

    def test_lapsed_false_for_trial_org(self):
        org = make_org(
            plan_tier="trial",
            subscription_status="trial",
            plan_expires_at=timezone.now() - timedelta(days=2),
        )
        assert org.is_lapsed is False

    def test_lapsed_false_when_plan_active(self):
        org = make_org(
            plan_tier="monthly",
            subscription_status="active",
            plan_expires_at=timezone.now() + timedelta(days=10),
        )
        assert org.is_lapsed is False

    def test_lapsed_false_when_no_expiry_set(self):
        org = make_org(
            plan_tier="monthly",
            subscription_status="past_due",
            plan_expires_at=None,
        )
        assert org.is_lapsed is False


# ---------------------------------------------------------------------------
# can_write_data
# ---------------------------------------------------------------------------

class TestCanWriteData:
    def test_write_blocked_for_lapsed_org(self):
        from apps.infrastructure.billing.features import can_write_data
        org = make_org(
            subscription_status="past_due",
            plan_expires_at=timezone.now() - timedelta(days=1),
        )
        assert can_write_data(org) is False

    def test_write_allowed_for_active_org(self):
        from apps.infrastructure.billing.features import can_write_data
        org = make_org(
            subscription_status="active",
            plan_expires_at=timezone.now() + timedelta(days=20),
        )
        assert can_write_data(org) is True

    def test_write_blocked_for_suspended_org(self):
        from apps.infrastructure.billing.features import can_write_data
        org = make_org(is_active=False)
        assert can_write_data(org) is False


# ---------------------------------------------------------------------------
# Write views — lapsed org is read-only
# ---------------------------------------------------------------------------

class TestWriteViewsLapsed:
    def _make_lapsed(self, org):
        org.subscription_status = "past_due"
        org.plan_expires_at = timezone.now() - timedelta(days=3)
        org.save(update_fields=["subscription_status", "plan_expires_at"])

    def test_mortality_post_returns_402_for_lapsed(
        self, client, tenant_user, test_batch
    ):
        self._make_lapsed(tenant_user.org)
        client.force_login(tenant_user)
        response = client.post(
            reverse("flocks:mortality", kwargs={"pk": test_batch.pk}),
            {"count": 3, "cause": "disease", "date": date.today()},
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 402
        assert b"expired" in response.content.lower()

    def test_lapsed_org_can_get_batch_detail(
        self, client, tenant_user, test_batch
    ):
        self._make_lapsed(tenant_user.org)
        client.force_login(tenant_user)
        response = client.get(
            reverse("flocks:detail", kwargs={"pk": test_batch.pk})
        )
        assert response.status_code == 200

    def test_active_org_can_post_mortality(
        self, client, tenant_user, test_batch
    ):
        # Control: an active org is not blocked by the lapsed gate.
        client.force_login(tenant_user)
        response = client.post(
            reverse("flocks:mortality", kwargs={"pk": test_batch.pk}),
            {"count": 2, "cause": "disease", "date": date.today()},
            HTTP_HX_REQUEST="true",
        )
        # 200 on success, 422 on validation error — never the 402 lapsed block.
        assert response.status_code != 402


# ---------------------------------------------------------------------------
# activate_plan clears lapsed state
# ---------------------------------------------------------------------------

class TestActivatePlanClearsLapsed:
    def test_renewal_clears_lapsed(self):
        from apps.infrastructure.billing.services import BillingService
        from apps.infrastructure.core.rls import set_tenant_context

        org = make_org(
            plan_tier="monthly",
            subscription_status="past_due",
            plan_expires_at=timezone.now() - timedelta(days=5),
        )
        assert org.is_lapsed is True

        with set_tenant_context(org):
            BillingService(org).activate_plan(
                plan_tier="monthly", activated_by="admin"
            )

        org.refresh_from_db()
        assert org.is_lapsed is False
        assert org.subscription_status == "active"
        assert org.plan_expires_at > timezone.now()


# ---------------------------------------------------------------------------
# Billing page button states
# ---------------------------------------------------------------------------

class TestBillingPageButtons:
    def _make_plans(self):
        make_plan("trial", 0)
        make_plan("cycle", 250000)
        make_plan("monthly", 500000)
        make_plan("yearly", 5000000, interval="annually")

    def test_no_downgrade_buttons(self, client, tenant_user):
        self._make_plans()
        client.force_login(tenant_user)
        response = client.get("/billing/")
        assert response.status_code == 200
        assert b"Downgrade" not in response.content

    def test_trial_card_shows_trial_already_used(self, client, tenant_user):
        # tenant_user.org is on the monthly plan, so the trial card must render
        # as a disabled "Trial already used" option.
        self._make_plans()
        client.force_login(tenant_user)
        response = client.get("/billing/")
        assert b"Trial already used" in response.content

    def test_cancel_subscription_section_present(self, client, tenant_user):
        self._make_plans()
        client.force_login(tenant_user)
        response = client.get("/billing/")
        assert b"Cancel subscription" in response.content
