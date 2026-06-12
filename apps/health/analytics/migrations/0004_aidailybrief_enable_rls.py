# Fixes a tenant-isolation gap found by tests/rls/test_rls_isolation.py:
# 0002_aidailybrief created the table WITHOUT calling enable_rls(), so
# analytics_aidailybrief had no row-level security — org briefs were only
# protected by the ORM manager (Layer 1), and any .unscoped()/raw query
# could read every org's briefs. Every TenantAwareModel migration must call
# enable_rls() (CLAUDE.md non-negotiable #2).
from django.db import migrations

from apps.infrastructure.core.migrations._rls_helpers import enable_rls


class Migration(migrations.Migration):

    dependencies = [
        ("analytics", "0003_farmbaseline"),
    ]

    operations = [
        *enable_rls("analytics_aidailybrief"),
    ]
