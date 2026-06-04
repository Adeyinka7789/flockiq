import uuid

from django.db import models


class ImpersonationLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    impersonator = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL, null=True,
        related_name='impersonation_sessions_started')
    target_user = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL, null=True,
        related_name='impersonation_sessions_received')
    target_org = models.ForeignKey(
        'tenants.Organization',
        on_delete=models.SET_NULL, null=True,
        related_name='impersonation_sessions')
    reason = models.CharField(max_length=200, blank=True, default='')
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ['-started_at']
        verbose_name = 'Impersonation Log'
        verbose_name_plural = 'Impersonation Logs'

    def __str__(self):
        return (f'{self.impersonator} → '
                f'{self.target_org} '
                f'({self.started_at.date()})')

    @property
    def duration_minutes(self):
        if self.ended_at:
            delta = self.ended_at - self.started_at
            return round(delta.total_seconds() / 60, 1)
        return None
