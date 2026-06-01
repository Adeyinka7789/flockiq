from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta


class Command(BaseCommand):
    help = 'Creates a test organization and owner user for development'

    def handle(self, *args, **kwargs):
        from apps.infrastructure.tenants.models import Organization
        from apps.infrastructure.accounts.models import CustomUser

        # Create test org
        org, created = Organization.objects.get_or_create(
            subdomain='testfarm',
            defaults={
                'name': 'Test Farm Ltd',
                'owner_name': 'Michael Adeniran',
                'owner_email': 'michael@testfarm.com',
                'owner_phone': '+2348012345678',
                'plan_tier': 'monthly',
                'subscription_status': 'active',
                'trial_ends_at': timezone.now() + timedelta(days=30),
                'is_active': True,
            }
        )
        if created:
            self.stdout.write(f'Created org: {org.name}')
        else:
            self.stdout.write(f'Org already exists: {org.name}')

        # Create owner user
        user, created = CustomUser.objects.get_or_create(
            email='michael@testfarm.com',
            defaults={
                'username': 'michael_testfarm',
                'first_name': 'Michael',
                'last_name': 'Adeniran',
                'org': org,
                'role': 'owner',
                'is_active': True,
            }
        )
        if created:
            user.set_password('TestFarm2026!')
            user.save()
            self.stdout.write(f'Created user: {user.email}')
        else:
            self.stdout.write(f'User already exists: {user.email}')

        self.stdout.write(self.style.SUCCESS(f'''
Test tenant ready:
  URL:      http://localhost:8000/
  Email:    michael@testfarm.com
  Password: TestFarm2026!
  Org:      {org.name} (subdomain: {org.subdomain})
        '''))
