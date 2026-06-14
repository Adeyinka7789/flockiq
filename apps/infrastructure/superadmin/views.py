import json
import time
from datetime import date, datetime, timedelta

import structlog
from django.conf import settings
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from apps.infrastructure.billing.models import PaymentRecord
from apps.infrastructure.core.email_service import EmailService
from apps.infrastructure.core.mixins import SuperAdminMixin
from apps.infrastructure.tenants.models import Organization

logger = structlog.get_logger(__name__)


def get_client_ip(request):
    """
    Capture both the trusted REMOTE_ADDR and the (client-spoofable)
    X-Forwarded-For header separately so the audit trail never relies on
    a header an attacker can set.
    """
    remote_addr = request.META.get('REMOTE_ADDR', '')
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR', '')
    return {
        'remote_addr': remote_addr,
        'x_forwarded_for': x_forwarded_for,
    }


def invalidate_org_active_cache(org_id):
    """Drop the TenantMiddleware org-active cache so suspension / activation
    takes effect on the org's very next request instead of after the TTL."""
    cache.delete(f'org_active:{org_id}')


def _org_owner(org):
    """Return the org's owner user (role='owner'), falling back to any member.

    Uses the reverse FK (related_name='users'), whose default manager is
    unscoped — safe here because superadmin runs without a tenant context.
    """
    owner = org.users.filter(role='owner').first()
    if not owner:
        owner = org.users.first()
    return owner


def send_suspension_email(org):
    """Notify the org owner that their account has been suspended."""
    owner = _org_owner(org)
    recipient = (owner.email if owner and owner.email else None) or org.owner_email
    if not recipient:
        return
    name = (owner.get_full_name() if owner else '') or recipient
    EmailService.send_suspension(
        recipient_email=recipient,
        owner_name=name,
        org_name=org.name,
        reason=org.suspension_reason,
    )


def send_reactivation_email(org):
    """Notify the org owner that their account has been reactivated."""
    owner = _org_owner(org)
    recipient = (owner.email if owner and owner.email else None) or org.owner_email
    if not recipient:
        return
    name = (owner.get_full_name() if owner else '') or recipient
    login_url = settings.SITE_URL.rstrip('/') + '/login/'
    EmailService.send_reactivation(
        recipient_email=recipient,
        owner_name=name,
        org_name=org.name,
        login_url=login_url,
    )


class SuperAdminDashboardView(SuperAdminMixin, View):
    def get(self, request):
        from apps.farm.flocks.models import Batch
        from apps.infrastructure.accounts.models import CustomUser

        today = date.today()

        total_orgs = Organization.objects.count()
        active_orgs = Organization.objects.filter(is_active=True).count()
        suspended_orgs = Organization.objects.filter(is_active=False).count()

        total_birds = (
            Batch.objects.unscoped()
            .filter(status='active')
            .aggregate(total=Sum('current_count'))['total'] or 0
        )

        this_month_start = timezone.make_aware(
            datetime.combine(today.replace(day=1), datetime.min.time())
        )
        mrr = (
            PaymentRecord.objects.unscoped()
            .filter(status='success', paid_at__gte=this_month_start)
            .aggregate(total=Sum('amount_kobo'))['total'] or 0
        )
        mrr_naira = mrr // 100

        revenue_trend = []
        for i in range(5, -1, -1):
            month_start = (today.replace(day=1) - timedelta(days=i * 30)).replace(day=1)
            if month_start.month == 12:
                month_end = month_start.replace(year=month_start.year + 1, month=1, day=1) - timedelta(days=1)
            else:
                month_end = month_start.replace(month=month_start.month + 1, day=1) - timedelta(days=1)

            rev = (
                PaymentRecord.objects.unscoped()
                .filter(
                    status='success',
                    paid_at__gte=timezone.make_aware(
                        datetime.combine(month_start, datetime.min.time())),
                    paid_at__lte=timezone.make_aware(
                        datetime.combine(month_end, datetime.max.time())),
                )
                .aggregate(total=Sum('amount_kobo'))['total'] or 0
            )
            revenue_trend.append({'month': month_start.strftime('%b').upper(), 'revenue': rev // 100})

        recent_orgs = Organization.objects.order_by('-created_at')[:5]

        total_users = CustomUser.objects.exclude(role='super_admin').count()

        total_payments = PaymentRecord.objects.unscoped().filter(status='success').count()
        total_rev = (
            PaymentRecord.objects.unscoped()
            .filter(status='success')
            .aggregate(total=Sum('amount_kobo'))['total'] or 0
        )
        avg_ticket = (total_rev // 100 // total_payments) if total_payments > 0 else 0

        context = {
            'total_orgs': total_orgs,
            'active_orgs': active_orgs,
            'suspended_orgs': suspended_orgs,
            'total_birds': total_birds,
            'mrr_naira': mrr_naira,
            'avg_ticket': avg_ticket,
            'revenue_trend': revenue_trend,
            'recent_orgs': recent_orgs,
            'total_users': total_users,
            'today': today,
        }
        return render(request, 'superadmin/dashboard.html', context)


class SuperAdminTenantsView(SuperAdminMixin, View):
    def get(self, request):
        from apps.farm.flocks.models import Batch

        status_filter = request.GET.get('status', 'all')
        plan_filter = request.GET.get('plan', 'all')
        q = request.GET.get('q', '').strip()

        orgs = Organization.objects.order_by('-created_at')

        if status_filter == 'active':
            orgs = orgs.filter(is_active=True)
        elif status_filter == 'suspended':
            orgs = orgs.filter(is_active=False)
        elif status_filter == 'lapsed':
            # Mirror of Organization.is_lapsed expressed as a queryset filter:
            # a paid plan that has expired and was not renewed.
            from django.utils import timezone
            orgs = (
                orgs.exclude(plan_tier='trial')
                .filter(plan_expires_at__lt=timezone.now())
                .exclude(subscription_status='active')
            )

        if plan_filter != 'all':
            orgs = orgs.filter(plan_tier=plan_filter)

        if q:
            orgs = orgs.filter(
                Q(name__icontains=q) |
                Q(owner_email__icontains=q) |
                Q(subdomain__icontains=q)
            )

        paginator = Paginator(orgs, 15)
        page_obj = paginator.get_page(request.GET.get('page', 1))

        bird_counts = {}
        for batch in (
            Batch.objects.unscoped()
            .filter(status='active')
            .values('org_id')
            .annotate(total=Sum('current_count'))
        ):
            bird_counts[batch['org_id']] = batch['total']

        org_list = [
            {'org': org, 'active_birds': bird_counts.get(org.pk, 0)}
            for org in page_obj
        ]

        context = {
            'page_obj': page_obj,
            'org_list': org_list,
            'total_count': paginator.count,
            'active_status': status_filter,
            'active_plan': plan_filter,
            'search_query': q,
            'plan_choices': [
                ('trial', 'Trial'), ('cycle', 'Cycle'),
                ('monthly', 'Monthly'), ('yearly', 'Yearly'),
            ],
        }

        if request.headers.get('HX-Request'):
            return render(request, 'superadmin/_tenant_table.html', context)
        return render(request, 'superadmin/tenants.html', context)


class SuperAdminTenantActionView(SuperAdminMixin, View):
    """Suspend, activate, or change plan for an org."""

    def post(self, request, pk):
        org = get_object_or_404(Organization, pk=pk)
        action = request.POST.get('action')

        if action == 'suspend':
            # Reason may arrive via the HTMX hx-prompt header or a POST field.
            reason = (request.headers.get('HX-Prompt')
                      or request.POST.get('suspension_reason', '')).strip()
            org.is_active = False
            org.suspension_reason = reason
            org.save()
            invalidate_org_active_cache(org.id)
            send_suspension_email(org)
            logger.info("superadmin.org_suspended", org_id=str(org.id), reason=reason)
            msg = f'{org.name} suspended.'
        elif action == 'activate':
            org.is_active = True
            org.suspension_reason = ''
            org.save()
            invalidate_org_active_cache(org.id)
            send_reactivation_email(org)
            logger.info("superadmin.org_activated", org_id=str(org.id))
            msg = f'{org.name} activated.'
        elif action == 'change_plan':
            new_plan = request.POST.get('plan_tier')
            if new_plan in ['trial', 'cycle', 'monthly', 'yearly']:
                from apps.infrastructure.billing.services import BillingService
                from apps.infrastructure.core.rls import set_tenant_context
                # Route through activate_plan so admin upgrades also set the
                # expiry window and fire the owner email + in-app notification.
                with set_tenant_context(org):
                    BillingService(org).activate_plan(
                        plan_tier=new_plan,
                        activated_by='admin',
                    )
                msg = f'{org.name} plan changed to {new_plan}.'
            else:
                msg = 'Invalid plan.'
        else:
            msg = 'Unknown action.'

        response = HttpResponse(status=204)
        response['HX-Trigger'] = json.dumps({'showToast': {'message': msg, 'type': 'success'}})
        response['HX-Refresh'] = 'true'
        return response


class SuspendOrgModalView(SuperAdminMixin, View):
    """GET — render the suspend-reason modal fragment into the global modal."""

    def get(self, request, pk):
        org = get_object_or_404(Organization, pk=pk)
        return render(request, 'superadmin/_suspend_modal.html', {'org': org})


class SuspendOrgView(SuperAdminMixin, View):
    """POST — suspend an org with a required reason and notify the owner.

    Returns the success fragment on completion, or re-renders the modal with an
    error if no reason was supplied. (Re-rendered at 200 — htmx 1.9.10 does not
    swap non-2xx responses, and the textarea's `required` attr is the first-line
    client-side guard.)
    """

    def post(self, request, pk):
        org = get_object_or_404(Organization, pk=pk)
        reason = request.POST.get('suspension_reason', '').strip()

        if not reason:
            return render(request, 'superadmin/_suspend_modal.html', {
                'org': org,
                'error': 'Please provide a reason for suspension.',
            })

        org.is_active = False
        org.suspension_reason = reason
        org.save(update_fields=['is_active', 'suspension_reason', 'updated_at'])
        invalidate_org_active_cache(org.id)
        send_suspension_email(org)
        logger.info("superadmin.org_suspended", org_id=str(org.id), reason=reason)

        return render(request, 'superadmin/_suspend_success.html', {
            'org': org,
            'owner': _org_owner(org),
        })


class BroadcastCreateView(SuperAdminMixin, View):
    def get(self, request):
        from apps.infrastructure.notifications.broadcast import get_broadcast_recipients
        counts = {
            'all': get_broadcast_recipients('all').count(),
            'owners': get_broadcast_recipients('owners').count(),
            'managers': get_broadcast_recipients('managers').count(),
            'owners_managers': get_broadcast_recipients('owners_managers').count(),
        }
        return render(request, 'superadmin/_broadcast_form.html', {'counts': counts})

    def post(self, request):
        from apps.infrastructure.notifications.models import BroadcastNotification
        from apps.infrastructure.notifications.broadcast import send_broadcast

        title = request.POST.get('title', '').strip()
        message = request.POST.get('message', '').strip()
        audience = request.POST.get('audience', 'owners_managers')
        channel = request.POST.get('channel', 'both')

        if not title or not message:
            from apps.infrastructure.notifications.broadcast import get_broadcast_recipients
            counts = {
                'all': get_broadcast_recipients('all').count(),
                'owners': get_broadcast_recipients('owners').count(),
                'managers': get_broadcast_recipients('managers').count(),
                'owners_managers': get_broadcast_recipients('owners_managers').count(),
            }
            return render(request, 'superadmin/_broadcast_form.html', {
                'error': 'Title and message are required.',
                'counts': counts,
            })

        broadcast = BroadcastNotification.objects.create(
            title=title,
            message=message,
            audience=audience,
            channel=channel,
            sent_by=request.user,
        )
        count = send_broadcast(broadcast)

        response = HttpResponse(status=204)
        response['HX-Trigger'] = json.dumps({
            'showToast': {
                'message': f'Broadcast sent to {count} users.',
                'type': 'success',
            },
            'close-modal': True,
        })
        return response


class BroadcastHistoryView(SuperAdminMixin, View):
    def get(self, request):
        from apps.infrastructure.notifications.models import BroadcastNotification
        broadcasts = BroadcastNotification.objects.order_by('-sent_at')[:20]
        return render(request, 'superadmin/broadcasts.html', {'broadcasts': broadcasts})


class SuperAdminAnalyticsView(SuperAdminMixin, View):
    def get(self, request):
        from apps.farm.flocks.models import Batch, MortalityLog

        today = date.today()

        total_orgs = Organization.objects.filter(is_active=True).count()

        total_birds = (
            Batch.objects.unscoped()
            .filter(status='active')
            .aggregate(total=Sum('current_count'))['total'] or 0
        )

        total_revenue = (
            PaymentRecord.objects.unscoped()
            .filter(status='success')
            .aggregate(total=Sum('amount_kobo'))['total'] or 0
        )
        total_revenue_naira = total_revenue // 100

        top_orgs_raw = (
            Batch.objects.unscoped()
            .filter(status='active')
            .values('org__name')
            .annotate(birds=Sum('current_count'))
            .order_by('-birds')[:5]
        )
        top_orgs = [
            {'name': r['org__name'][:12].upper(), 'birds': r['birds']}
            for r in top_orgs_raw
        ]

        top_revenue_orgs = []
        for org in Organization.objects.filter(is_active=True).order_by('-created_at')[:5]:
            org_revenue = (
                PaymentRecord.objects.unscoped()
                .filter(org=org, status='success')
                .aggregate(total=Sum('amount_kobo'))['total'] or 0
            )

            org_birds = (
                Batch.objects.unscoped()
                .filter(org=org, status='active')
                .count()
            )

            org_mort = (
                MortalityLog.objects.unscoped()
                .filter(batch__org=org, date__gte=today - timedelta(days=30))
                .aggregate(total=Sum('count'))['total'] or 0
            )

            org_live = (
                Batch.objects.unscoped()
                .filter(org=org, status='active')
                .aggregate(total=Sum('current_count'))['total'] or 1
            )

            mort_rate = round(org_mort / max(org_live, 1) * 100, 1)

            top_revenue_orgs.append({
                'org': org,
                'revenue': org_revenue // 100,
                'active_flocks': org_birds,
                'mort_rate': mort_rate,
            })

        top_revenue_orgs.sort(key=lambda x: x['revenue'], reverse=True)

        context = {
            'total_orgs': total_orgs,
            'total_birds': total_birds,
            'total_revenue_naira': total_revenue_naira,
            'top_orgs': top_orgs,
            'top_revenue_orgs': top_revenue_orgs,
            'today': today,
        }
        return render(request, 'superadmin/analytics.html', context)


class BillingControlView(SuperAdminMixin, View):
    def get(self, request):
        from apps.infrastructure.billing.models import PaymentRecord
        from django.db.models import Sum, Q
        from datetime import date, timedelta

        today = date.today()
        this_month = timezone.make_aware(
            datetime.combine(today.replace(day=1), datetime.min.time())
        )

        mrr = PaymentRecord.objects.unscoped().filter(
            status='success',
            paid_at__gte=this_month,
        ).aggregate(total=Sum('amount_kobo'))['total'] or 0
        mrr_naira = mrr // 100

        active_trials = Organization.objects.filter(
            subscription_status='trial',
            is_active=True,
        ).count()

        past_due = Organization.objects.filter(
            subscription_status__in=['past_due', 'suspended'],
        ).count()

        grace_period = Organization.objects.filter(
            grace_period_ends_at__gte=timezone.now(),
        ).count()

        q = request.GET.get('q', '').strip()
        status_filter = request.GET.get('status', 'all')

        orgs = Organization.objects.order_by('-created_at')
        if status_filter != 'all':
            orgs = orgs.filter(subscription_status=status_filter)
        if q:
            orgs = orgs.filter(
                Q(name__icontains=q) |
                Q(owner_email__icontains=q))

        org_list = []
        for org in orgs[:50]:
            last_payment = PaymentRecord.objects.unscoped().filter(
                org=org, status='success'
            ).order_by('-paid_at').first()

            next_invoice = None
            if last_payment and last_payment.plan:
                interval = last_payment.plan.billing_interval
                if last_payment.paid_at:
                    if interval == 'monthly':
                        next_invoice = (
                            last_payment.paid_at.date() + timedelta(days=30))
                    elif interval == 'annually':
                        next_invoice = (
                            last_payment.paid_at.date() + timedelta(days=365))

            org_list.append({
                'org': org,
                'last_payment': last_payment,
                'next_invoice': next_invoice,
            })

        context = {
            'mrr_naira': mrr_naira,
            'active_trials': active_trials,
            'past_due': past_due,
            'grace_period': grace_period,
            'org_list': org_list,
            'status_filter': status_filter,
            'search_query': q,
        }

        if request.headers.get('HX-Request'):
            return render(request, 'superadmin/_billing_table.html', context)
        return render(request, 'superadmin/billing.html', context)


class BillingManageOrgView(SuperAdminMixin, View):
    def get(self, request, pk):
        from datetime import date
        org = get_object_or_404(Organization, pk=pk)
        return render(request,
            'superadmin/_billing_manage_panel.html',
            {'org': org, 'today': date.today()})

    def post(self, request, pk):
        from datetime import datetime, timedelta
        org = get_object_or_404(Organization, pk=pk)
        action = request.POST.get('action')

        if action == 'grace_period':
            end_date = request.POST.get('grace_end_date')
            if end_date:
                naive = datetime.strptime(end_date, '%Y-%m-%d')
                org.grace_period_ends_at = timezone.make_aware(naive)
                org.subscription_status = 'active'
                org.is_active = True
                org.save()
                invalidate_org_active_cache(org.id)
                msg = f'Grace period set for {org.name}'
            else:
                msg = 'End date required'

        elif action == 'extend_trial':
            days = int(request.POST.get('days', 7))
            if org.trial_ends_at:
                org.trial_ends_at += timedelta(days=days)
            else:
                org.trial_ends_at = timezone.now() + timedelta(days=days)
            org.subscription_status = 'trial'
            org.save()
            msg = f'Trial extended by {days} days for {org.name}'

        elif action == 'change_status':
            new_status = request.POST.get('status')
            if new_status in ['active', 'trial', 'suspended', 'past_due', 'cancelled']:
                org.subscription_status = new_status
                org.is_active = new_status == 'active'
                org.save()
                invalidate_org_active_cache(org.id)
                if not org.is_active:
                    send_suspension_email(org)
                msg = f'{org.name} status → {new_status}'
            else:
                msg = 'Invalid status'

        else:
            msg = 'Unknown action'

        response = HttpResponse(status=204)
        response['HX-Trigger'] = json.dumps({
            'showToast': {'message': msg, 'type': 'success'},
        })
        response['HX-Refresh'] = 'true'
        return response


class ImpersonationView(SuperAdminMixin, View):
    def get(self, request):
        from apps.infrastructure.accounts.models import CustomUser
        from apps.infrastructure.accounts.impersonation import ImpersonationLog

        q = request.GET.get('q', '').strip()
        role_filter = request.GET.get('role', '')

        users = CustomUser.objects.filter(
            is_active=True
        ).exclude(
            role='super_admin'
        ).select_related('org').order_by('-last_login')

        if q:
            users = users.filter(
                Q(email__icontains=q) |
                Q(org__name__icontains=q) |
                Q(first_name__icontains=q) |
                Q(last_name__icontains=q))

        if role_filter:
            users = users.filter(role=role_filter)

        recent_logs = ImpersonationLog.objects.select_related(
            'impersonator', 'target_user', 'target_org'
        ).order_by('-started_at')[:10]

        context = {
            'users': users[:50],
            'recent_logs': recent_logs,
            'search_query': q,
            'role_filter': role_filter,
        }

        if request.headers.get('HX-Request'):
            return render(
                request, 'superadmin/_impersonation_table.html', context)
        return render(request, 'superadmin/impersonation.html', context)


class ImpersonateStartView(SuperAdminMixin, View):
    """Start impersonating a user."""

    def post(self, request, user_pk):
        from apps.infrastructure.accounts.models import CustomUser
        from apps.infrastructure.accounts.impersonation import ImpersonationLog

        target = get_object_or_404(CustomUser, pk=user_pk, is_active=True)

        if target.role == 'super_admin' or target.is_superuser:
            response = HttpResponse(status=400)
            response['HX-Trigger'] = json.dumps({
                'showToast': {
                    'message': 'Cannot impersonate super admin.',
                    'type': 'error'
                }
            })
            return response

        ip_info = get_client_ip(request)

        request.session['_impersonator_id'] = str(request.user.pk)
        request.session['_impersonated_user_id'] = str(target.pk)
        request.session['_impersonation_started_at'] = time.time()
        request.session.modified = True

        ImpersonationLog.objects.create(
            impersonator=request.user,
            target_user=target,
            target_org=target.org,
            reason=request.POST.get('reason', ''),
            ip_address=ip_info['remote_addr'] or None,
            x_forwarded_for=ip_info['x_forwarded_for'],
        )

        from django.shortcuts import redirect
        return redirect('dashboard')


class ImpersonateStopView(View):
    """Stop impersonation and return to super admin."""

    def post(self, request):
        from apps.infrastructure.accounts.impersonation import ImpersonationLog

        impersonated_id = request.session.get('_impersonated_user_id')

        if impersonated_id:
            try:
                from apps.infrastructure.accounts.models import CustomUser
                target = CustomUser.objects.get(pk=impersonated_id)
                log = ImpersonationLog.objects.filter(
                    target_user=target,
                    ended_at__isnull=True,
                ).order_by('-started_at').first()
                if log:
                    log.ended_at = timezone.now()
                    log.save()
            except Exception:
                logger.exception("impersonation.stop_log_failed",
                                 user_id=str(request.user.pk))

        request.session.pop('_impersonated_user_id', None)
        request.session.pop('_impersonator_id', None)
        request.session.modified = True

        from django.shortcuts import redirect
        return redirect('superadmin:impersonation')


class TenantQuotasView(SuperAdminMixin, View):
    def get(self, request):
        from apps.infrastructure.accounts.models import CustomUser
        from apps.infrastructure.core.rls import no_tenant_context
        from apps.farm.flocks.models import Batch

        total_orgs = Organization.objects.count()
        active_orgs = Organization.objects.filter(is_active=True).count()

        org_list = []
        for org in Organization.objects.filter(is_active=True).order_by('name'):
            user_count = CustomUser.objects.filter(
                org=org, is_active=True).count()

            with no_tenant_context():
                bird_count = Batch.objects.filter(
                    org=org, status='active'
                ).aggregate(total=Sum('current_count'))['total'] or 0

            user_pct = min(100, round(
                user_count / max(org.max_users, 1) * 100))
            storage_pct = min(100, round(
                1 / max(org.storage_quota_gb, 1) * 100))

            org_list.append({
                'org': org,
                'user_count': user_count,
                'user_pct': user_pct,
                'storage_pct': storage_pct,
                'bird_count': bird_count,
            })

        context = {
            'total_orgs': total_orgs,
            'active_orgs': active_orgs,
            'org_list': org_list,
        }
        return render(request, 'superadmin/tenant_quotas.html', context)


class TenantQuotaEditView(SuperAdminMixin, View):
    """HTMX panel to edit quota limits for a tenant."""

    def get(self, request, pk):
        org = get_object_or_404(Organization, pk=pk)
        return render(request, 'superadmin/_quota_edit_panel.html', {'org': org})

    def post(self, request, pk):
        org = get_object_or_404(Organization, pk=pk)

        try:
            max_users = int(request.POST.get('max_users', 5))
            storage_gb = int(request.POST.get('storage_quota_gb', 5))
            org.max_users = max(1, max_users)
            org.storage_quota_gb = max(1, storage_gb)
            org.save()
            msg = f'Quotas updated for {org.name}'
        except (ValueError, TypeError):
            msg = 'Invalid quota values'

        response = HttpResponse(status=204)
        response['HX-Trigger'] = json.dumps({
            'showToast': {'message': msg, 'type': 'success'},
        })
        response['HX-Refresh'] = 'true'
        return response


class SystemHealthView(SuperAdminMixin, View):
    def get(self, request):
        from django_celery_results.models import TaskResult
        from django_celery_beat.models import PeriodicTask
        from datetime import date, timedelta

        today = date.today()

        redis_info = {}
        workers_running = 0
        queue_size = 0
        try:
            from django_redis import get_redis_connection
            redis_conn = get_redis_connection('default')
            info = redis_conn.info()
            redis_info = {
                'connected_clients': info.get('connected_clients', 0),
                'used_memory_human': info.get('used_memory_human', '—'),
                'uptime_days': info.get('uptime_in_days', 0),
            }
            queue_size = redis_conn.llen('celery') or 0
            workers_running = info.get('connected_clients', 1)
        except Exception:
            logger.exception("system_health.redis_unavailable")

        recent_tasks = TaskResult.objects.order_by('-date_done')[:20]

        failed_today = TaskResult.objects.filter(
            status='FAILURE',
            date_done__date=today,
        ).count()

        total_recent = TaskResult.objects.filter(
            date_done__date__gte=today - timedelta(days=7)
        ).count()
        success_recent = TaskResult.objects.filter(
            status='SUCCESS',
            date_done__date__gte=today - timedelta(days=7)
        ).count()
        success_rate = round(success_recent / max(total_recent, 1) * 100, 1)

        periodic_tasks = PeriodicTask.objects.filter(
            enabled=True).order_by('name')[:10]

        context = {
            'redis_info': redis_info,
            'workers_running': workers_running,
            'queue_size': queue_size,
            'recent_tasks': recent_tasks,
            'failed_today': failed_today,
            'success_rate': success_rate,
            'periodic_tasks': periodic_tasks,
            'today': today,
        }
        return render(request, 'superadmin/system_health.html', context)


class AuditTrailView(SuperAdminMixin, View):
    def get(self, request):
        from auditlog.models import LogEntry
        from django.core.paginator import Paginator
        from django.db.models import Q
        from datetime import date, timedelta

        today = date.today()

        tenant_id = request.GET.get('tenant', '')
        action_filter = request.GET.get('action', '')
        q = request.GET.get('q', '').strip()
        date_from = request.GET.get('date_from', '')
        date_to = request.GET.get('date_to', '')

        logs = LogEntry.objects.select_related(
            'actor', 'content_type'
        ).order_by('-timestamp')

        if tenant_id:
            logs = logs.filter(actor__org_id=tenant_id)

        if action_filter == 'create':
            logs = logs.filter(action=LogEntry.Action.CREATE)
        elif action_filter == 'update':
            logs = logs.filter(action=LogEntry.Action.UPDATE)
        elif action_filter == 'delete':
            logs = logs.filter(action=LogEntry.Action.DELETE)

        if q:
            logs = logs.filter(
                Q(actor__email__icontains=q) |
                Q(object_repr__icontains=q) |
                Q(changes__icontains=q))

        if date_from:
            from datetime import datetime
            logs = logs.filter(
                timestamp__date__gte=datetime.strptime(date_from, '%Y-%m-%d').date())
        if date_to:
            from datetime import datetime
            logs = logs.filter(
                timestamp__date__lte=datetime.strptime(date_to, '%Y-%m-%d').date())

        paginator = Paginator(logs, 20)
        page_obj = paginator.get_page(request.GET.get('page', 1))

        this_week = today - timedelta(days=7)
        last_week = today - timedelta(days=14)
        this_week_count = LogEntry.objects.filter(
            timestamp__date__gte=this_week).count()
        last_week_count = LogEntry.objects.filter(
            timestamp__date__gte=last_week,
            timestamp__date__lt=this_week).count()

        all_orgs = Organization.objects.filter(is_active=True).order_by('name')

        context = {
            'page_obj': page_obj,
            'total_count': paginator.count,
            'all_orgs': all_orgs,
            'active_tenant': tenant_id,
            'active_action': action_filter,
            'search_query': q,
            'date_from': date_from,
            'date_to': date_to,
            'this_week_count': this_week_count,
            'last_week_count': last_week_count,
            'today': today,
            'LogEntry': LogEntry,
        }

        if request.headers.get('HX-Request'):
            return render(request, 'superadmin/_audit_table.html', context)
        return render(request, 'superadmin/audit_trail.html', context)


class SupportTicketsView(SuperAdminMixin, View):
    def get(self, request):
        from apps.infrastructure.notifications.models import SupportTicket

        status_filter = request.GET.get('status', 'all')
        priority_filter = request.GET.get('priority', 'all')

        tickets = SupportTicket.objects.select_related('org', 'submitted_by').order_by('-created_at')

        if status_filter != 'all':
            tickets = tickets.filter(status=status_filter)
        if priority_filter != 'all':
            tickets = tickets.filter(priority=priority_filter)

        paginator = Paginator(tickets, 20)
        page_obj = paginator.get_page(request.GET.get('page', 1))

        context = {
            'page_obj': page_obj,
            'total_count': paginator.count,
            'unread_count': SupportTicket.objects.filter(is_read_by_admin=False).count(),
            'open_count': SupportTicket.objects.filter(status='open').count(),
            'high_priority_count': SupportTicket.objects.filter(priority='high', status__in=['open', 'in_progress']).count(),
            'active_status': status_filter,
            'active_priority': priority_filter,
        }
        return render(request, 'superadmin/support_tickets.html', context)


class SupportTicketMarkReadView(SuperAdminMixin, View):
    def post(self, request, pk):
        from apps.infrastructure.notifications.models import SupportTicket

        ticket = get_object_or_404(SupportTicket, pk=pk)
        ticket.is_read_by_admin = not ticket.is_read_by_admin
        ticket.save(update_fields=['is_read_by_admin'])

        label = 'Marked as read' if ticket.is_read_by_admin else 'Marked as unread'
        new_unread = SupportTicket.objects.filter(is_read_by_admin=False).count()
        oob_html = (
            '<div id="unread-count-value" hx-swap-oob="true" '
            'style="font-size:22px;font-weight:800;color:#3d5a99;margin-top:2px;">'
            f'{new_unread}</div>'
        )
        response = HttpResponse(oob_html, status=200)
        response['HX-Trigger'] = json.dumps({'showToast': {'message': label, 'type': 'success'}})
        return response


class SupportTicketDetailView(SuperAdminMixin, View):
    def get(self, request, pk):
        from apps.infrastructure.notifications.models import SupportTicket

        ticket = get_object_or_404(SupportTicket, pk=pk)
        if not ticket.is_read_by_admin:
            ticket.is_read_by_admin = True
            ticket.save(update_fields=['is_read_by_admin'])

        replies = ticket.replies.select_related('author').all()
        context = {
            'ticket': ticket,
            'replies': replies,
        }
        return render(request, 'superadmin/support_ticket_detail.html', context)


class TenantDetailView(SuperAdminMixin, View):
    def get(self, request, pk):
        from apps.infrastructure.core.rls import set_tenant_context
        from apps.infrastructure.notifications.models import SupportTicket
        from django.contrib.auth import get_user_model
        from django.db.models import Count, Q

        User = get_user_model()
        org = get_object_or_404(Organization, pk=pk)

        with set_tenant_context(org):
            from apps.farm.farms.models import Farm
            from apps.farm.flocks.models import Batch
            from apps.infrastructure.billing.models import PaymentRecord
            from apps.infrastructure.core.credit_scoring import CreditScoringService

            farms = list(
                Farm.objects.annotate(
                    houses_count=Count('houses', distinct=True),
                    active_batches_count=Count(
                        'houses__batches',
                        filter=Q(houses__batches__status='active'),
                        distinct=True,
                    ),
                )
            )
            active_batches = list(
                Batch.objects.filter(status='active')
                .select_related('farm', 'house')
            )
            total_live_birds = sum(b.current_count for b in active_batches)
            payments = list(PaymentRecord.objects.order_by('-paid_at')[:10])
            credit_score = CreditScoringService.get_latest(org)

        support_tickets = list(
            SupportTicket.objects.filter(org=org).order_by('-created_at')[:10]
        )
        team_members = list(
            User.objects.filter(org=org).order_by('role', 'email')
        )
        owner = next((u for u in team_members if u.role == 'owner'), None)

        context = {
            'org': org,
            'owner': owner,
            'team_members': team_members,
            'farms': farms,
            'active_batches': active_batches,
            'total_live_birds': total_live_birds,
            'payments': payments,
            'support_tickets': support_tickets,
            'farms_count': len(farms),
            'batches_count': len(active_batches),
            'credit_score': credit_score,
        }
        return render(request, 'superadmin/tenant_detail.html', context)


class DeletedRecordsView(SuperAdminMixin, View):
    """View and restore soft-deleted records across all tenants.

    PostgreSQL RLS only exposes a tenant's rows while a matching GUC is active,
    so listing fans out per org inside set_tenant_context(org); restore is given
    the record's org_id by the template and re-enters that org's context.
    """

    # name → Model. Restore POST looks the model up here.
    def _model_map(self):
        from apps.farm.farms.models import Farm, House
        from apps.farm.flocks.models import Batch, MortalityLog, WeightRecord
        from apps.production.feed.models import FeedLog
        from apps.production.production.models import EggProductionLog
        from apps.production.water.models import WaterLog

        return {
            'farm': Farm,
            'house': House,
            'batch': Batch,
            'mortality': MortalityLog,
            'weight': WeightRecord,
            'feed': FeedLog,
            'egg': EggProductionLog,
            'water': WaterLog,
        }

    def get(self, request):
        from apps.farm.farms.models import Farm, House
        from apps.farm.flocks.models import Batch
        from apps.infrastructure.core.rls import no_tenant_context, set_tenant_context

        # Organization has RLS disabled — safe to enumerate without a context.
        with no_tenant_context():
            orgs = list(Organization.objects.order_by('name'))

        deleted_farms, deleted_houses, deleted_batches = [], [], []
        for org in orgs:
            with set_tenant_context(org):
                # GUC = this org, so all_objects (tenant-scoped, deleted included)
                # returns this org's deleted rows. select_related on FKs is
                # evaluated inside the context where the relations are visible.
                deleted_farms += list(
                    Farm.all_objects.filter(is_deleted=True)
                    .select_related('deleted_by')
                )
                deleted_houses += list(
                    House.all_objects.filter(is_deleted=True)
                    .select_related('farm', 'deleted_by')
                )
                deleted_batches += list(
                    Batch.all_objects.filter(is_deleted=True)
                    .select_related('farm', 'deleted_by')
                )

        deleted_farms.sort(key=lambda o: o.deleted_at or timezone.now(), reverse=True)
        deleted_houses.sort(key=lambda o: o.deleted_at or timezone.now(), reverse=True)
        deleted_batches.sort(key=lambda o: o.deleted_at or timezone.now(), reverse=True)

        context = {
            'deleted_farms': deleted_farms[:50],
            'deleted_houses': deleted_houses[:50],
            'deleted_batches': deleted_batches[:50],
        }
        return render(request, 'superadmin/deleted_records.html', context)

    def post(self, request):
        """Restore a soft-deleted record. Needs model, pk and org_id."""
        from apps.infrastructure.core.rls import set_tenant_context

        model_name = request.POST.get('model')
        pk = request.POST.get('pk')
        org_id = request.POST.get('org_id')

        Model = self._model_map().get(model_name)
        if not Model or not pk or not org_id:
            return HttpResponse(status=400)

        # Re-enter the record's tenant context so RLS exposes it for the restore.
        with set_tenant_context(org_id):
            obj = get_object_or_404(Model.all_objects, pk=pk, is_deleted=True)
            obj.restore(user=request.user)
            obj_label = str(obj)

        logger.info(
            "superadmin.record_restored",
            model=Model.__name__,
            object_id=str(pk),
            org_id=str(org_id),
            restored_by=str(request.user.pk),
        )

        response = HttpResponse(status=204)
        response['HX-Trigger'] = json.dumps({
            'showToast': {'message': f'Restored: {obj_label}', 'type': 'success'},
        })
        response['HX-Refresh'] = 'true'
        return response


class ValuationSettingsView(SuperAdminMixin, View):
    """Superadmin-editable platform fallback valuation prices.

    Backs FlockValuationService priority 3 (admin fallback) — the figures used
    when a batch has no farmer override and the org has no MarketPrice data.
    """

    def get(self, request):
        from apps.infrastructure.billing.models import ValuationSettings
        return render(request, 'superadmin/valuation_settings.html', {
            'valuation_settings': ValuationSettings.get_current(),
        })

    def post(self, request):
        from decimal import Decimal, InvalidOperation
        from apps.infrastructure.billing.models import ValuationSettings

        row = ValuationSettings.get_current()
        fields = (
            'broiler_price_per_kg',
            'layer_point_of_lay_price',
            'generic_per_bird_price',
        )

        errors, cleaned = {}, {}
        for field in fields:
            raw = request.POST.get(field, '').strip()
            try:
                value = Decimal(raw)
            except (InvalidOperation, ValueError):
                errors[field] = 'Enter a valid number.'
                continue
            if value <= 0:
                errors[field] = 'Price must be greater than zero.'
            else:
                cleaned[field] = value

        if errors:
            return render(request, 'superadmin/valuation_settings.html', {
                'valuation_settings': row,
                'errors': errors,
                'submitted': request.POST,
            }, status=422)

        for field, value in cleaned.items():
            setattr(row, field, value)
        row.updated_by = request.user
        row.save()
        logger.info('superadmin.valuation_settings_updated',
                    updated_by=str(request.user.pk))

        return render(request, 'superadmin/valuation_settings.html', {
            'valuation_settings': row,
            'saved': True,
        })


class SupportTicketReplyView(SuperAdminMixin, View):
    def post(self, request, pk):
        from django.conf import settings as django_settings
        from apps.infrastructure.core.email_service import EmailService
        from apps.infrastructure.notifications.models import (
            SupportTicket, SupportTicketReply,
        )
        from apps.infrastructure.core.rls import set_tenant_context

        ticket = get_object_or_404(SupportTicket, pk=pk)
        message = request.POST.get('message', '').strip()
        new_status = request.POST.get('status', '').strip()

        if not message:
            replies = ticket.replies.select_related('author').all()
            return render(
                request,
                'superadmin/_ticket_replies.html',
                {'ticket': ticket, 'replies': replies, 'error': 'Reply cannot be empty.'},
                status=422,
            )

        reply = SupportTicketReply.objects.create(
            ticket=ticket,
            author=request.user,
            message=message,
        )

        if new_status in ('open', 'in_progress', 'resolved'):
            ticket.status = new_status
            ticket.save(update_fields=['status', 'updated_at'])

        if ticket.submitted_by:
            base_url = getattr(django_settings, 'SITE_URL', 'https://app.flockiq.com')
            ticket_url = f"{base_url.rstrip('/')}/support/my-tickets/{ticket.pk}/"
            EmailService.send_support_reply(
                recipient_email=ticket.submitted_by.email,
                owner_name=ticket.submitted_by.get_full_name() or ticket.submitted_by.email,
                subject=ticket.subject,
                reply_message=message,
                ticket_url=ticket_url,
            )

            # Write to NotificationLog (tenant-scoped) so the user's bell lights up.
            # AdminNotification is for superadmin-only; tenant users' bells read NotificationLog.
            # Routed through notify() for the _should_receive gate. support_reply is
            # intentionally uncategorised (no preference toggle and not financial),
            # so it always reaches the ticket's submitter regardless of role/prefs.
            from apps.infrastructure.notifications.services import NotificationService
            with set_tenant_context(ticket.org):
                NotificationService(ticket.org).notify(
                    recipient=ticket.submitted_by,
                    event_type='support_reply',
                    title=f"Support ticket update — {ticket.subject}",
                    body=f"Admin replied: {reply.message[:200]}",
                    severity='info',
                    action_url=reverse('notifications:support_ticket_detail', kwargs={'pk': ticket.pk}),
                )

        replies = ticket.replies.select_related('author').all()
        return render(
            request,
            'superadmin/_ticket_replies.html',
            {'ticket': ticket, 'replies': replies},
        )
