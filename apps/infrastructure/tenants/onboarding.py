# CORRECTED: apps/infrastructure/tenants/onboarding.py
# Includes: proper tenant checks, async DB operations via Celery, exception handling

from datetime import date
import structlog
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render
from django.views import View
from django.http import Http404

logger = structlog.get_logger(__name__)


class OnboardingWizardView(LoginRequiredMixin, View):
    """
    Onboarding wizard with async farm/house/batch creation.
    CRITICAL FIX: Tenant context is checked before accessing org properties.
    Heavy DB operations (create_farm, create_house, create_batch) offloaded to Celery.
    """

    def get(self, request):
        org = getattr(request.user, 'org', None)
        if not org:
            return redirect('/')
        if org.onboarding_complete:
            return redirect('/')
        step = int(request.GET.get('step', 1))
        return render(request, 'tenants/onboarding.html', {
            'step': step,
            'org': org,
        })

    def post(self, request):
        step = int(request.POST.get('step', 1))
        
        # CRITICAL FIX: Check org exists before any attribute access
        org = getattr(request.user, 'org', None)
        if not org:
            logger.warning("onboarding.no_org", user_id=str(request.user.id))
            return redirect('/')

        if step == 1:
            return self._handle_step_1(request, org)
        elif step == 2:
            return self._handle_step_2(request, org)
        elif step == 3:
            return self._handle_step_3(request, org)

        return redirect('/onboarding/')

    def _handle_step_1(self, request, org):
        """Step 1: Create farm asynchronously"""
        from apps.farm.farms.tasks import create_farm_async
        
        try:
            farm_name = request.POST.get('farm_name', '').strip()
            location = request.POST.get('location', '').strip()
            lat = request.POST.get('latitude', '')
            lng = request.POST.get('longitude', '')
            farm_type = request.POST.get('farm_type', 'mixed')

            if not farm_name or not location:
                return render(
                    request,
                    'tenants/onboarding.html',
                    {
                        'step': 1,
                        'error': 'Farm name and location are required.',
                        'org': org,
                    },
                    status=422,
                )

            # ASYNC: Offload farm creation to Celery
            task = create_farm_async.delay(
                org_id=str(org.id),
                name=farm_name,
                location=location,
                lat=lat,
                lng=lng,
                farm_type=farm_type,
            )
            request.session['onboarding_task_id'] = task.id
            
            logger.info("onboarding.farm_creation_started", org_id=str(org.id), task_id=task.id)
            return redirect('/onboarding/?step=2')
            
        except Exception as e:
            logger.exception("onboarding.step1_handler_error", org_id=str(org.id))
            return render(
                request,
                'tenants/onboarding.html',
                {
                    'step': 1,
                    'error': 'An unexpected error occurred. Please try again.',
                    'org': org,
                },
                status=422,
            )

    def _handle_step_2(self, request, org):
        """Step 2: Create house asynchronously"""
        from apps.farm.farms.tasks import create_house_async
        from apps.farm.farms.models import Farm
        from apps.infrastructure.core.rls import set_tenant_context

        try:
            # Retrieve farm, with exception handling
            try:
                with set_tenant_context(org):
                    farm = Farm.objects.first()
                    if not farm:
                        return render(
                            request,
                            'tenants/onboarding.html',
                            {
                                'step': 2,
                                'error': 'No farm found. Please complete Step 1 first.',
                                'org': org,
                            },
                            status=422,
                        )
            except Farm.DoesNotExist:
                return render(
                    request,
                    'tenants/onboarding.html',
                    {
                        'step': 2,
                        'error': 'Farm not found. Please restart the onboarding.',
                        'org': org,
                    },
                    status=422,
                )

            house_name = request.POST.get('house_name', '').strip()
            capacity_str = request.POST.get('capacity', '500').strip()
            house_type = request.POST.get('house_type', 'mixed')

            if not house_name:
                return render(
                    request,
                    'tenants/onboarding.html',
                    {
                        'step': 2,
                        'error': 'House name is required.',
                        'org': org,
                    },
                    status=422,
                )

            try:
                capacity = int(capacity_str)
                if capacity < 100:
                    raise ValueError("Capacity must be at least 100 birds.")
            except ValueError as e:
                return render(
                    request,
                    'tenants/onboarding.html',
                    {
                        'step': 2,
                        'error': f'Invalid capacity: {str(e)}',
                        'org': org,
                    },
                    status=422,
                )

            # ASYNC: Offload house creation to Celery
            task = create_house_async.delay(
                org_id=str(org.id),
                farm_id=str(farm.id),
                name=house_name,
                capacity=capacity,
                house_type=house_type,
            )
            request.session['onboarding_task_id'] = task.id
            
            logger.info("onboarding.house_creation_started", org_id=str(org.id), farm_id=str(farm.id), task_id=task.id)
            return redirect('/onboarding/?step=3')

        except Exception as e:
            logger.exception("onboarding.step2_handler_error", org_id=str(org.id))
            return render(
                request,
                'tenants/onboarding.html',
                {
                    'step': 2,
                    'error': 'An unexpected error occurred. Please try again.',
                    'org': org,
                },
                status=422,
            )

    def _handle_step_3(self, request, org):
        """Step 3: Create batch asynchronously and complete onboarding"""
        from apps.farm.farms.models import Farm, House
        from apps.farm.flocks.tasks import create_batch_async
        from apps.infrastructure.core.rls import set_tenant_context

        try:
            # Retrieve farm and house with exception handling
            try:
                with set_tenant_context(org):
                    farm = Farm.objects.first()
                    house = House.objects.first()
                    
                    if not farm or not house:
                        missing = []
                        if not farm:
                            missing.append("farm")
                        if not house:
                            missing.append("house")
                        return render(
                            request,
                            'tenants/onboarding.html',
                            {
                                'step': 3,
                                'error': f'Missing: {", ".join(missing)}. Please restart onboarding.',
                                'org': org,
                            },
                            status=422,
                        )
            except (Farm.DoesNotExist, House.DoesNotExist) as e:
                return render(
                    request,
                    'tenants/onboarding.html',
                    {
                        'step': 3,
                        'error': 'Required farm or house not found. Please restart onboarding.',
                        'org': org,
                    },
                    status=422,
                )

            batch_name = request.POST.get('batch_name', '').strip()
            bird_type = request.POST.get('bird_type', 'broiler')
            bird_count_str = request.POST.get('bird_count', '200').strip()
            breed_name = request.POST.get('breed_name', '').strip()

            if not batch_name:
                return render(
                    request,
                    'tenants/onboarding.html',
                    {
                        'step': 3,
                        'error': 'Batch name is required.',
                        'org': org,
                    },
                    status=422,
                )

            if bird_type not in ['broiler', 'layer']:
                return render(
                    request,
                    'tenants/onboarding.html',
                    {
                        'step': 3,
                        'error': 'Invalid bird type.',
                        'org': org,
                    },
                    status=422,
                )

            try:
                initial_count = int(bird_count_str)
                if initial_count < 10:
                    raise ValueError("Initial count must be at least 10 birds.")
            except ValueError as e:
                return render(
                    request,
                    'tenants/onboarding.html',
                    {
                        'step': 3,
                        'error': f'Invalid bird count: {str(e)}',
                        'org': org,
                    },
                    status=422,
                )

            # ASYNC: Offload batch creation to Celery
            task = create_batch_async.delay(
                org_id=str(org.id),
                farm_id=str(farm.id),
                house_id=str(house.id),
                batch_name=batch_name,
                bird_type=bird_type,
                placement_date=str(date.today()),
                initial_count=initial_count,
                breed_name=breed_name,
            )
            request.session['onboarding_task_id'] = task.id
            
            # Mark onboarding complete in background after batch creation
            org.onboarding_complete = True
            org.save(update_fields=['onboarding_complete', 'updated_at'])
            
            logger.info("onboarding.completed", org_id=str(org.id), batch_name=batch_name, task_id=task.id)
            return redirect('/?welcome=1')

        except Exception as e:
            logger.exception("onboarding.step3_handler_error", org_id=str(org.id))
            return render(
                request,
                'tenants/onboarding.html',
                {
                    'step': 3,
                    'error': 'An unexpected error occurred. Please try again.',
                    'org': org,
                },
                status=422,
            )
