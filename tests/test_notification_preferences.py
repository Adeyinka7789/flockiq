"""
Tests for the personal Notification Preferences page and the preference-aware
notification dispatch gate (`_should_receive`).

Covers:
  - GET / POST on the preferences view (auth, saving, role-gated fields)
  - Template RBAC: financial / system categories hidden from restricted roles
  - `_should_receive` honouring personal mutes AND the existing RBAC floor
"""
import pytest

pytestmark = pytest.mark.django_db

PREFS_URL = "/settings/notifications/"


def _make_user(org, role, suffix):
    from apps.infrastructure.accounts.models import CustomUser
    return CustomUser.objects.create_user(
        username=f"{role}-{suffix}",
        email=f"{role}-{suffix}@{org.subdomain}.com",
        password="testpass123",
        org=org,
        role=role,
        first_name=role.title(),
        last_name="User",
        email_verified=True,
    )


# ── View: GET / POST ──────────────────────────────────────────────────────────

class TestNotificationPreferencesView:

    def test_requires_login(self, client):
        response = client.get(PREFS_URL)
        assert response.status_code in (301, 302)

    def test_get_returns_200(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.get(PREFS_URL)
        assert response.status_code == 200

    def test_post_saves_sms_alerts_on(self, client, tenant_user):
        tenant_user.sms_alerts_enabled = False
        tenant_user.save(update_fields=["sms_alerts_enabled"])
        client.force_login(tenant_user)
        response = client.post(PREFS_URL, {"sms_alerts": "on"}, HTTP_HX_REQUEST="true")
        assert response.status_code == 200
        tenant_user.refresh_from_db()
        assert tenant_user.sms_alerts_enabled is True

    def test_post_saves_sms_alerts_off(self, client, tenant_user):
        # tenant_user starts with sms_alerts_enabled=True (default).
        client.force_login(tenant_user)
        response = client.post(PREFS_URL, {}, HTTP_HX_REQUEST="true")
        assert response.status_code == 200
        tenant_user.refresh_from_db()
        assert tenant_user.sms_alerts_enabled is False

    def test_post_saves_email_digest_frequency(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.post(
            PREFS_URL,
            {"email_digest_frequency": "daily"},
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        tenant_user.refresh_from_db()
        assert tenant_user.email_digest_frequency == "daily"

    def test_hx_post_returns_saved_toast(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.post(PREFS_URL, {"sms_alerts": "on"}, HTTP_HX_REQUEST="true")
        assert response.status_code == 200
        assert b"Saved" in response.content

    def test_non_hx_post_redirects(self, client, tenant_user):
        client.force_login(tenant_user)
        response = client.post(PREFS_URL, {"sms_alerts": "on"})
        assert response.status_code in (301, 302)


# ── View: role-gated financial / system fields ────────────────────────────────

class TestRoleGatedFields:

    def test_data_entry_cannot_set_financial_reports(self, client, test_org):
        user = _make_user(test_org, "data_entry", "fin")
        user.notify_financial_reports = False
        user.save(update_fields=["notify_financial_reports"])

        client.force_login(user)
        # Even if a data_entry user forges the field, the view must ignore it.
        response = client.post(
            PREFS_URL,
            {"notify_financial_reports": "on"},
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        user.refresh_from_db()
        assert user.notify_financial_reports is False

    def test_data_entry_cannot_set_system_updates(self, client, test_org):
        user = _make_user(test_org, "data_entry", "sys")
        user.notify_system_updates = False
        user.save(update_fields=["notify_system_updates"])

        client.force_login(user)
        response = client.post(
            PREFS_URL,
            {"notify_system_updates": "on"},
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        user.refresh_from_db()
        assert user.notify_system_updates is False

    def test_owner_can_set_financial_reports(self, client, tenant_user):
        tenant_user.notify_financial_reports = True
        tenant_user.save(update_fields=["notify_financial_reports"])
        client.force_login(tenant_user)
        # Omitting the checkbox should turn it off for an owner.
        response = client.post(PREFS_URL, {}, HTTP_HX_REQUEST="true")
        assert response.status_code == 200
        tenant_user.refresh_from_db()
        assert tenant_user.notify_financial_reports is False


# ── Template: category visibility by role ─────────────────────────────────────

class TestCategoryVisibility:

    def test_owner_sees_all_categories(self, client, tenant_user):
        client.force_login(tenant_user)
        content = client.get(PREFS_URL).content
        assert b"Health Alerts" in content
        assert b"Production Insights" in content
        assert b"Financial Reports" in content
        assert b"System Updates" in content

    def test_manager_sees_all_categories(self, client, test_org):
        user = _make_user(test_org, "manager", "vis")
        client.force_login(user)
        content = client.get(PREFS_URL).content
        assert b"Financial Reports" in content
        assert b"System Updates" in content

    def test_data_entry_hidden_financial_and_system(self, client, test_org):
        user = _make_user(test_org, "data_entry", "vis")
        client.force_login(user)
        content = client.get(PREFS_URL).content
        assert b"Health Alerts" in content
        assert b"Production Insights" in content
        assert b"Financial Reports" not in content
        assert b"System Updates" not in content

    def test_vet_advisor_hidden_financial_and_system(self, client, test_org):
        user = _make_user(test_org, "vet_advisor", "vis")
        client.force_login(user)
        content = client.get(PREFS_URL).content
        assert b"Financial Reports" not in content
        assert b"System Updates" not in content


# ── _should_receive: personal mutes + RBAC floor ──────────────────────────────

class TestShouldReceive:

    def test_muted_health_category_blocks(self, test_org):
        from apps.infrastructure.notifications.services import _should_receive
        user = _make_user(test_org, "owner", "mute-health")
        user.notify_health_alerts = False
        user.save(update_fields=["notify_health_alerts"])
        assert _should_receive(user, "mortality_spike") is False

    def test_muted_production_category_blocks(self, test_org):
        from apps.infrastructure.notifications.services import _should_receive
        user = _make_user(test_org, "owner", "mute-prod")
        user.notify_production_insights = False
        user.save(update_fields=["notify_production_insights"])
        assert _should_receive(user, "production_drop") is False

    def test_muted_system_category_blocks(self, test_org):
        from apps.infrastructure.notifications.services import _should_receive
        user = _make_user(test_org, "owner", "mute-sys")
        user.notify_system_updates = False
        user.save(update_fields=["notify_system_updates"])
        assert _should_receive(user, "platform_update") is False

    def test_owner_can_mute_financial_category(self, test_org):
        from apps.infrastructure.notifications.services import _should_receive
        user = _make_user(test_org, "owner", "mute-fin")
        user.notify_financial_reports = False
        user.save(update_fields=["notify_financial_reports"])
        # An *informational* financial event is muteable by preference.
        # (payment_failed / expiry reminders are NOT — see TestAlwaysDeliver.)
        assert _should_receive(user, "billing_plan_activated") is False
        assert _should_receive(user, "billing_upgrade_scheduled") is False

    def test_active_category_allows(self, test_org):
        from apps.infrastructure.notifications.services import _should_receive
        user = _make_user(test_org, "owner", "active")
        # All categories default to enabled.
        assert _should_receive(user, "mortality_spike") is True
        assert _should_receive(user, "production_drop") is True

    def test_rbac_floor_overrides_personal_pref(self, test_org):
        """Restricted roles never get financial events, even if not muted."""
        from apps.infrastructure.notifications.services import _should_receive
        user = _make_user(test_org, "data_entry", "floor")
        # notify_financial_reports defaults True — the RBAC floor must still block.
        assert user.notify_financial_reports is True
        assert _should_receive(user, "payment_failed") is False

    def test_unmapped_event_always_allowed(self, test_org):
        from apps.infrastructure.notifications.services import _should_receive
        user = _make_user(test_org, "owner", "unmapped")
        assert _should_receive(user, "batch_closed") is True

    def test_ai_anomaly_and_support_reply_always_allowed(self, test_org):
        """ai_anomaly and support_reply are intentionally uncategorised: no
        preference toggle maps to them, so they are never silently muted."""
        from apps.infrastructure.notifications.services import _should_receive
        owner = _make_user(test_org, "owner", "uncat-owner")
        owner.notify_health_alerts = False
        owner.notify_production_insights = False
        owner.notify_system_updates = False
        owner.notify_financial_reports = False
        owner.save()
        assert _should_receive(owner, "ai_anomaly") is True
        assert _should_receive(owner, "support_reply") is True


# ── _should_receive: account-critical events bypass the preference mute ────────

class TestAlwaysDeliver:
    """payment_failed and plan/trial expiry reminders bypass the personal
    category mute (a muted owner must still hear that their account is at risk),
    but they remain subject to the RBAC floor."""

    ALWAYS = ["payment_failed", "billing_expiry_reminder", "trial_expiry_reminder"]

    @pytest.mark.parametrize("event_type", ALWAYS)
    def test_owner_cannot_mute_account_critical(self, test_org, event_type):
        from apps.infrastructure.notifications.services import _should_receive
        user = _make_user(test_org, "owner", f"crit-{event_type}")
        user.notify_financial_reports = False
        user.save(update_fields=["notify_financial_reports"])
        assert _should_receive(user, event_type) is True

    @pytest.mark.parametrize("event_type", ALWAYS)
    @pytest.mark.parametrize("role", ["data_entry", "vet_advisor"])
    def test_rbac_floor_still_blocks_restricted_roles(self, test_org, event_type, role):
        """Always-deliver does NOT punch through the RBAC floor — these events
        carry billing detail and still must not reach restricted roles."""
        from apps.infrastructure.notifications.services import _should_receive
        user = _make_user(test_org, role, f"floor-{role}-{event_type}")
        assert _should_receive(user, event_type) is False
