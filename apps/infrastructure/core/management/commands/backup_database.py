import datetime
import glob
import os
import subprocess

import structlog
from django.conf import settings
from django.core.management.base import BaseCommand

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "Backup PostgreSQL database to local and remote storage"

    def handle(self, *args, **options):
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = getattr(settings, "BACKUP_DIR", "/var/backups/flockiq")
        os.makedirs(backup_dir, exist_ok=True)

        filename = f"flockiq_{timestamp}.dump"
        filepath = os.path.join(backup_dir, filename)

        db = settings.DATABASES["default"]
        env = os.environ.copy()
        env["PGPASSWORD"] = db.get("PASSWORD", "")

        dump_cmd = [
            "pg_dump",
            "-h", db.get("HOST", "localhost"),
            "-p", str(db.get("PORT", 5432)),
            "-U", db.get("USER", "flockiq_app"),
            "-d", db.get("NAME", "flockiq"),
            "--no-password",
            "--format=custom",
        ]

        try:
            with open(filepath, "wb") as f:
                subprocess.run(
                    dump_cmd,
                    stdout=f,
                    stderr=subprocess.PIPE,
                    env=env,
                    check=True,
                )

            size_mb = os.path.getsize(filepath) / (1024 * 1024)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Backup created: {filename} ({size_mb:.1f} MB)"
                )
            )
            logger.info("backup.created", filename=filename, size_mb=round(size_mb, 1))

            self._upload_to_remote(filepath, filename)
            self._cleanup_old_backups(backup_dir)

        except subprocess.CalledProcessError as e:
            self.stderr.write(f"Backup failed: {e.stderr.decode()}")
            logger.error("backup.failed", error=e.stderr.decode())
            raise

    def _upload_to_remote(self, filepath, filename):
        bucket = getattr(settings, "BACKUP_B2_BUCKET", "")
        if not bucket:
            self.stdout.write("No remote backup configured (set BACKUP_B2_BUCKET)")
            return

        try:
            import boto3

            s3 = boto3.client(
                "s3",
                endpoint_url=getattr(settings, "BACKUP_B2_ENDPOINT", ""),
                aws_access_key_id=getattr(settings, "BACKUP_B2_KEY_ID", ""),
                aws_secret_access_key=getattr(settings, "BACKUP_B2_APP_KEY", ""),
            )
            s3.upload_file(filepath, bucket, f"backups/{filename}")
            self.stdout.write(self.style.SUCCESS(f"Uploaded to B2: {filename}"))
            logger.info("backup.uploaded", filename=filename, bucket=bucket)
        except Exception as e:
            self.stderr.write(f"Remote upload failed: {e}")
            logger.error("backup.upload_failed", error=str(e))
            # Local backup still succeeded — do not raise.

    def _cleanup_old_backups(self, backup_dir, keep=7):
        backups = sorted(
            glob.glob(os.path.join(backup_dir, "*.dump"))
            + glob.glob(os.path.join(backup_dir, "*.sql.gz"))
        )
        for old in backups[:-keep]:
            os.remove(old)
            self.stdout.write(f"Removed old backup: {old}")
            logger.info("backup.pruned", path=old)
