from datetime import date

from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render
from django.views import View


class OnboardingWizardView(LoginRequiredMixin, View):
    def get(self, request):
        if not request.user.org:
            return redirect('/')
        if request.user.org.onboarding_complete:
            return redirect('/')
        step = int(request.GET.get('step', 1))
        return render(request, 'tenants/onboarding.html', {
            'step': step,
            'org': request.user.org,
        })

    def post(self, request):
        step = int(request.POST.get('step', 1))
        org = request.user.org

        if step == 1:
            from apps.farm.farms.services import FarmService
            from apps.infrastructure.core.rls import set_tenant_context
            with set_tenant_context(org):
                try:
                    FarmService(org).create_farm(
                        name=request.POST.get('farm_name'),
                        location=request.POST.get('location'),
                        lat=request.POST.get('latitude'),
                        lng=request.POST.get('longitude'),
                        farm_type=request.POST.get('farm_type', 'mixed'),
                    )
                    return redirect('/onboarding/?step=2')
                except Exception as e:
                    return render(request, 'tenants/onboarding.html',
                                  {'step': 1, 'error': str(e), 'org': org})

        elif step == 2:
            from apps.farm.farms.services import FarmService
            from apps.farm.farms.models import Farm
            from apps.infrastructure.core.rls import set_tenant_context
            with set_tenant_context(org):
                farm = Farm.objects.first()
                if farm:
                    try:
                        FarmService(org).create_house(
                            farm_id=str(farm.pk),
                            name=request.POST.get('house_name'),
                            capacity=int(request.POST.get('capacity', 500)),
                            house_type=request.POST.get('house_type', 'mixed'),
                        )
                        return redirect('/onboarding/?step=3')
                    except Exception as e:
                        return render(request, 'tenants/onboarding.html',
                                      {'step': 2, 'error': str(e),
                                       'org': org, 'farm': farm})

        elif step == 3:
            from apps.farm.flocks.services import BatchService
            from apps.farm.farms.models import Farm, House
            from apps.infrastructure.core.rls import set_tenant_context
            with set_tenant_context(org):
                farm = Farm.objects.first()
                house = House.objects.first()
                if farm and house:
                    try:
                        BatchService(org).create_batch(
                            farm_id=str(farm.pk),
                            house_id=str(house.pk),
                            batch_name=request.POST.get('batch_name'),
                            bird_type=request.POST.get('bird_type', 'broiler'),
                            placement_date=date.today(),
                            initial_count=int(request.POST.get('bird_count', 200)),
                            breed_name=request.POST.get('breed_name', ''),
                        )
                        org.onboarding_complete = True
                        org.save(update_fields=['onboarding_complete', 'updated_at'])
                        return redirect('/?welcome=1')
                    except Exception as e:
                        return render(request, 'tenants/onboarding.html',
                                      {'step': 3, 'error': str(e),
                                       'org': org})

        return redirect('/onboarding/')
