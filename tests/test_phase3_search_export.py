"""Phase 3 — search/filter and PDF/Excel export tests.

Covers:
  * Batch list search by name and filter by status.
  * Farm list search by name/location.
  * HTMX requests return the list *partial*, not the full page.
  * Feed log table date/feed-type filtering.
  * Batch PDF/Excel exports return the correct content-type.
  * Exports are plan-gated for trial organisations.

RULE: these are written but not run here — run locally with
    pytest tests/test_phase3_search_export.py -v
"""
import datetime
import uuid
from decimal import Decimal

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_farm(org, name="Test Farm", location="Lagos", farm_type="mixed"):
    from apps.farm.farms.models import Farm
    from apps.infrastructure.core.rls import set_tenant_context
    with set_tenant_context(org):
        farm = Farm(
            org=org,
            name=name,
            location=location,
            latitude=Decimal("6.5244"),
            longitude=Decimal("3.3792"),
            farm_type=farm_type,
        )
        farm.clean()
        farm.save()
    return farm


def _make_house(org, farm, name="House A"):
    from apps.farm.farms.models import House
    from apps.infrastructure.core.rls import set_tenant_context
    with set_tenant_context(org):
        return House.objects.create(
            org=org, farm=farm, name=name, capacity=500, house_type="layer",
        )


def _make_batch(org, farm, house, name, status="active", bird_type="layer"):
    from apps.farm.flocks.models import Batch
    from apps.infrastructure.core.rls import set_tenant_context
    with set_tenant_context(org):
        return Batch.objects.create(
            org=org,
            farm=farm,
            house=house,
            batch_name=name,
            bird_type=bird_type,
            placement_date=datetime.date.today(),
            initial_count=200,
            current_count=200,
            status=status,
        )


@pytest.fixture
def trial_org(db):
    from apps.infrastructure.tenants.models import Organization
    return Organization.objects.create(
        name="Trial Farm Ltd",
        subdomain=f"trialfarm-{uuid.uuid4().hex[:8]}",
        plan_tier="trial",
        subscription_status="trialing",
        onboarding_complete=True,
        is_active=True,
    )


@pytest.fixture
def trial_user(db, trial_org):
    from apps.infrastructure.accounts.models import CustomUser
    return CustomUser.objects.create_user(
        username=f"owner-{trial_org.subdomain}",
        email=f"owner@{trial_org.subdomain}.com",
        password="testpass123",
        org=trial_org,
        role="owner",
        email_verified=True,
    )


# ── Batch list search/filter (Item 9) ───────────────────────────────────────

class TestBatchListSearch:

    def test_search_by_name_matches_only_relevant_batch(
        self, client, tenant_user, test_org, test_farm, test_house
    ):
        _make_batch(test_org, test_farm, test_house, "Broiler Alpha")
        _make_batch(test_org, test_farm, test_house, "Layer Beta")
        client.force_login(tenant_user)

        resp = client.get(reverse("flocks:list"), {"q": "Alpha", "status": "all"})
        assert resp.status_code == 200
        assert b"Broiler Alpha" in resp.content
        assert b"Layer Beta" not in resp.content

    def test_filter_by_status_returns_only_matching(
        self, client, tenant_user, test_org, test_farm, test_house
    ):
        _make_batch(test_org, test_farm, test_house, "Active Flock", status="active")
        _make_batch(test_org, test_farm, test_house, "Closed Flock", status="closed")
        client.force_login(tenant_user)

        # Request the HTMX partial so we assert against only the filtered list,
        # not the full page (whose nav/sidebar can mention other batches).
        resp = client.get(
            reverse("flocks:list"), {"status": "closed"}, HTTP_HX_REQUEST="true"
        )
        assert resp.status_code == 200
        assert b"Closed Flock" in resp.content
        assert b"Active Flock" not in resp.content

    def test_htmx_request_returns_partial_not_full_page(
        self, client, tenant_user, test_org, test_farm, test_house
    ):
        _make_batch(test_org, test_farm, test_house, "Broiler Alpha")
        client.force_login(tenant_user)

        full = client.get(reverse("flocks:list"))
        partial = client.get(reverse("flocks:list"), HTTP_HX_REQUEST="true")

        assert full.status_code == partial.status_code == 200
        # The search bar lives in the full-page template, outside the swap target.
        assert b"Search batches" in full.content
        assert b"Search batches" not in partial.content


# ── Farm list search/filter (Item 9) ────────────────────────────────────────

class TestFarmListSearch:

    def test_search_by_name(self, client, tenant_user, test_org):
        _make_farm(test_org, name="Lagos Layers", location="Lagos")
        _make_farm(test_org, name="Kano Broilers", location="Kano")
        client.force_login(tenant_user)

        resp = client.get(reverse("farms:list"), {"q": "Kano"})
        assert resp.status_code == 200
        assert b"Kano Broilers" in resp.content
        assert b"Lagos Layers" not in resp.content

    def test_filter_by_farm_type(self, client, tenant_user, test_org):
        _make_farm(test_org, name="Layer Site", farm_type="layer")
        _make_farm(test_org, name="Broiler Site", farm_type="broiler")
        client.force_login(tenant_user)

        resp = client.get(reverse("farms:list"), {"farm_type": "broiler"})
        assert resp.status_code == 200
        assert b"Broiler Site" in resp.content
        assert b"Layer Site" not in resp.content

    def test_htmx_request_returns_grid_partial(self, client, tenant_user, test_org):
        _make_farm(test_org, name="Lagos Layers")
        client.force_login(tenant_user)

        full = client.get(reverse("farms:list"))
        partial = client.get(reverse("farms:list"), HTTP_HX_REQUEST="true")

        assert full.status_code == partial.status_code == 200
        assert b"Search farms" in full.content
        assert b"Search farms" not in partial.content


# ── Feed log filtering (Item 9) ──────────────────────────────────────────────

class TestFeedTableFilter:

    def _log(self, org, batch, record_date, feed_type, qty="50"):
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.production.feed.services import FeedService
        with set_tenant_context(org):
            FeedService(org).log_feed(
                batch_id=str(batch.id),
                record_date=record_date,
                feed_type=feed_type,
                quantity_kg=qty,
            )

    def test_filter_by_feed_type(
        self, client, tenant_user, test_org, test_farm, test_house
    ):
        batch = _make_batch(test_org, test_farm, test_house, "Feed Batch")
        today = datetime.date.today()
        self._log(test_org, batch, today, "layer_mash")
        self._log(test_org, batch, today - datetime.timedelta(days=1), "starter")
        client.force_login(tenant_user)

        resp = client.get(
            reverse("feed:table", args=[batch.id]), {"feed_type": "starter"}
        )
        assert resp.status_code == 200
        # 1 record matches the starter filter.
        assert b"1 record" in resp.content


# ── Exports (Item 10) ────────────────────────────────────────────────────────

class TestBatchExports:

    def test_pdf_export_returns_pdf_content_type(
        self, client, tenant_user, test_org, test_batch
    ):
        # test_org is on the monthly plan → pdf_export enabled.
        client.force_login(tenant_user)
        resp = client.get(reverse("flocks:export_pdf", args=[test_batch.id]))
        assert resp.status_code == 200
        assert resp["Content-Type"] == "application/pdf"
        assert resp["Content-Disposition"].startswith("attachment")

    def test_excel_export_returns_xlsx_content_type(
        self, client, tenant_user, test_org, test_batch
    ):
        client.force_login(tenant_user)
        resp = client.get(reverse("flocks:export_excel", args=[test_batch.id]))
        assert resp.status_code == 200
        assert resp["Content-Type"] == (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    def test_pdf_export_gated_for_trial_org(self, client, trial_user, trial_org):
        # Build a batch under the trial org.
        farm = _make_farm(trial_org)
        house = _make_house(trial_org, farm)
        batch = _make_batch(trial_org, farm, house, "Trial Batch")

        client.force_login(trial_user)
        resp = client.get(reverse("flocks:export_pdf", args=[batch.id]))

        # Gated path returns a toast trigger, never a PDF payload.
        assert resp.status_code == 200
        assert resp["Content-Type"] != "application/pdf"
        assert "HX-Trigger" in resp
        assert b"%PDF" not in resp.content

    def test_excel_export_gated_for_trial_org(self, client, trial_user, trial_org):
        farm = _make_farm(trial_org)
        house = _make_house(trial_org, farm)
        batch = _make_batch(trial_org, farm, house, "Trial Batch XL")

        client.force_login(trial_user)
        resp = client.get(reverse("flocks:export_excel", args=[batch.id]))

        assert resp.status_code == 200
        assert resp["Content-Type"] != (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        assert "HX-Trigger" in resp


# ── Feed table wired into detail pages (Item 9 follow-up) ────────────────────

class TestFeedTableWiring:

    def test_batch_detail_includes_feed_table_loader(
        self, client, tenant_user, test_org, test_batch
    ):
        client.force_login(tenant_user)
        resp = client.get(reverse("flocks:detail", args=[test_batch.id]))
        assert resp.status_code == 200
        assert b"Feed Records" in resp.content
        # The section lazy-loads the (now filterable) feed table partial.
        assert reverse("feed:table", args=[test_batch.id]).encode() in resp.content
        assert b"feedLogged from:body" in resp.content

    def test_farm_detail_includes_feed_table_loader(
        self, client, tenant_user, test_org, test_farm, test_house, test_batch
    ):
        client.force_login(tenant_user)
        resp = client.get(reverse("farms:detail", args=[test_farm.id]))
        assert resp.status_code == 200
        assert b"Recent Feed Logs" in resp.content
        # Farm page wires the first active batch's feed table.
        assert reverse("feed:table", args=[test_batch.id]).encode() in resp.content
