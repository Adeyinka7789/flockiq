import json
from collections import Counter
from datetime import date, timedelta

from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views import View

from apps.infrastructure.billing.models import PaymentRecord
from apps.infrastructure.core.mixins import SuperAdminMixin
from apps.infrastructure.tenants.models import Organization


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

        this_month_start = today.replace(day=1)
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
                .filter(status='success', paid_at__gte=month_start, paid_at__lte=month_end)
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
        return render(request, 'superadmin/tenants.html', context)


class SuperAdminTenantActionView(SuperAdminMixin, View):
    """Suspend, activate, or change plan for an org."""

    def post(self, request, pk):
        org = get_object_or_404(Organization, pk=pk)
        action = request.POST.get('action')

        if action == 'suspend':
            org.is_active = False
            org.save()
            msg = f'{org.name} suspended.'
        elif action == 'activate':
            org.is_active = True
            org.save()
            msg = f'{org.name} activated.'
        elif action == 'change_plan':
            new_plan = request.POST.get('plan_tier')
            if new_plan in ['trial', 'cycle', 'monthly', 'yearly']:
                org.plan_tier = new_plan
                org.save()
                msg = f'{org.name} plan changed to {new_plan}.'
            else:
                msg = 'Invalid plan.'
        else:
            msg = 'Unknown action.'

        response = HttpResponse(status=204)
        response['HX-Trigger'] = json.dumps({'showToast': {'message': msg, 'type': 'success'}})
        response['HX-Refresh'] = 'true'
        return response


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
