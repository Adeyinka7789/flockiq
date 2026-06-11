"""
Phase 4 production-readiness fixes.

Covers:
  FIX 2  — backup_database command creates a local dump file
  FIX 3  — check_celery_beat_seeded warns when fewer than 10 tasks registered
  FIX 3  — check_paystack_webhook_secret raises Error when secret missing in prod
  FIX 4B — check_disk_space fires Sentry when usage > 80%
  FIX 7  — check_database_role_security passes for a non-superuser role
"""

import os
import shutil
import tempfile
import uuid
from unittest.mock import MagicMock, call, patch

import pytest
from django.test import override_settings

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# FIX 2 — backup_database management command
# ---------------------------------------------------------------------------

class TestBackupDatabaseCommand:
    def test_creates_dump_file(self):
        """Command writes a .dump file to BACKUP_DIR."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with override_settings(BACKUP_DIR=tmpdir):
                # Fake pg_dump succeeds and writes some bytes.
                fake_proc = MagicMock(returncode=0, stderr=b"")

                def fake_run(cmd, stdout, stderr, env, check):
                    stdout.write(b"fake-dump-data")
                    return fake_proc

                with patch("subprocess.run", side_effect=fake_run):
                    from django.core.management import call_command
                    call_command("backup_database", verbosity=0)

                dumps = [f for f in os.listdir(tmpdir) if f.endswith(".dump")]
                assert len(dumps) == 1
                assert dumps[0].startswith("flockiq_")

    def test_cleanup_keeps_last_7(self):
        """Old backups beyond the last 7 are removed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Pre-create 9 old .dump files so cleanup has something to prune.
            for i in range(9):
                open(os.path.join(tmpdir, f"flockiq_200001{i:02d}_000000.dump"), "w").close()

            with override_settings(BACKUP_DIR=tmpdir):
                fake_proc = MagicMock(returncode=0, stderr=b"")

                def fake_run(cmd, stdout, stderr, env, check):
                    stdout.write(b"data")
                    return fake_proc

                with patch("subprocess.run", side_effect=fake_run):
                    from django.core.management import call_command
                    call_command("backup_database", verbosity=0)

                dumps = sorted(
                    f for f in os.listdir(tmpdir) if f.endswith(".dump")
                )
                assert len(dumps) == 7


# ---------------------------------------------------------------------------
# FIX 3 — check_celery_beat_seeded
# ---------------------------------------------------------------------------

class TestCheckCeleryBeatSeeded:
    def test_warns_when_fewer_than_10_tasks(self):
        from apps.infrastructure.billing.checks import check_celery_beat_seeded

        mock_pt = MagicMock()
        mock_pt.objects.count.return_value = 3

        with patch.dict(
            "sys.modules",
            {"django_celery_beat.models": MagicMock(PeriodicTask=mock_pt)},
        ):
            errors = check_celery_beat_seeded(None)

        assert any(e.id == "billing.W002" for e in errors)

    def test_no_warning_when_10_or_more_tasks(self):
        from apps.infrastructure.billing.checks import check_celery_beat_seeded

        mock_pt = MagicMock()
        mock_pt.objects.count.return_value = 12

        with patch.dict(
            "sys.modules",
            {"django_celery_beat.models": MagicMock(PeriodicTask=mock_pt)},
        ):
            errors = check_celery_beat_seeded(None)

        assert errors == []


# ---------------------------------------------------------------------------
# FIX 3 — check_paystack_webhook_secret
# ---------------------------------------------------------------------------

class TestCheckPaystackWebhookSecret:
    def test_error_in_production_when_secret_missing(self):
        from apps.infrastructure.billing.checks import check_paystack_webhook_secret

        with override_settings(DEBUG=False, PAYSTACK_WEBHOOK_SECRET=""):
            errors = check_paystack_webhook_secret(None)

        ids = [e.id for e in errors]
        assert "billing.E001" in ids

    def test_warning_in_debug_when_secret_missing(self):
        from apps.infrastructure.billing.checks import check_paystack_webhook_secret

        with override_settings(DEBUG=True, PAYSTACK_WEBHOOK_SECRET=""):
            errors = check_paystack_webhook_secret(None)

        ids = [e.id for e in errors]
        assert "billing.W001" in ids

    def test_passes_when_secret_present(self):
        from apps.infrastructure.billing.checks import check_paystack_webhook_secret

        with override_settings(
            DEBUG=False, PAYSTACK_WEBHOOK_SECRET="sk_live_abc123"
        ):
            errors = check_paystack_webhook_secret(None)

        assert errors == []


# ---------------------------------------------------------------------------
# FIX 4B — check_disk_space task
# ---------------------------------------------------------------------------

class TestCheckDiskSpaceTask:
    def test_fires_sentry_when_usage_exceeds_80_pct(self):
        """Sentry capture_message is called when disk > 80%."""
        # 90% usage: used=90, free=10, total=100 (arbitrary units)
        fake_usage = (100, 90, 10)

        with patch("shutil.disk_usage", return_value=fake_usage):
            with patch("sentry_sdk.capture_message") as mock_capture:
                from apps.infrastructure.core.tasks import check_disk_space
                check_disk_space()

        mock_capture.assert_called_once()
        msg = mock_capture.call_args[0][0]
        assert "90.0%" in msg

    def test_no_sentry_when_usage_below_80_pct(self):
        """Sentry is not called when disk usage is healthy."""
        fake_usage = (100, 50, 50)

        with patch("shutil.disk_usage", return_value=fake_usage):
            with patch("sentry_sdk.capture_message") as mock_capture:
                from apps.infrastructure.core.tasks import check_disk_space
                check_disk_space()

        mock_capture.assert_not_called()


# ---------------------------------------------------------------------------
# FIX 7 — check_database_role_security
# ---------------------------------------------------------------------------

def _make_cursor_ctx(fetchone_return):
    """Build a context-manager mock for connection.cursor()."""
    cursor = MagicMock()
    cursor.fetchone.return_value = fetchone_return
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=cursor)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


class TestCheckDatabaseRoleSecurity:
    def test_passes_for_non_superuser_non_bypassrls(self):
        from apps.infrastructure.core.checks import check_database_role_security

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = _make_cursor_ctx((False, False))

        with patch("apps.infrastructure.core.checks.connection", mock_conn):
            errors = check_database_role_security(None)

        assert errors == []

    def test_error_for_superuser(self):
        from apps.infrastructure.core.checks import check_database_role_security

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = _make_cursor_ctx((True, False))

        with patch("apps.infrastructure.core.checks.connection", mock_conn):
            errors = check_database_role_security(None)

        assert any(e.id == "core.E001" for e in errors)

    def test_error_for_bypassrls(self):
        from apps.infrastructure.core.checks import check_database_role_security

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = _make_cursor_ctx((False, True))

        with patch("apps.infrastructure.core.checks.connection", mock_conn):
            errors = check_database_role_security(None)

        assert any(e.id == "core.E002" for e in errors)

    def test_warning_on_db_exception(self):
        from apps.infrastructure.core.checks import check_database_role_security

        mock_conn = MagicMock()
        mock_conn.cursor.side_effect = Exception("connection refused")

        with patch("apps.infrastructure.core.checks.connection", mock_conn):
            errors = check_database_role_security(None)

        assert any(e.id == "core.W001" for e in errors)
