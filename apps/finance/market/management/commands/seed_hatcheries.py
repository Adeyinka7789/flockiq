from django.core.management.base import BaseCommand


SEED_DATA = [
    {
        "name": "Zartech Limited",
        "state": "Lagos",
        "lga": "Ikeja",
        "address": "Km 47, Lagos-Ibadan Expressway, Lagos",
        "phone": "0802-000-0001",
        "website": "https://zartech.com.ng",
        "bird_types": ["broiler", "layer"],
    },
    {
        "name": "Sayed Farms",
        "state": "Oyo",
        "lga": "Ibadan North",
        "address": "Ibadan, Oyo State",
        "phone": "0803-000-0002",
        "website": "",
        "bird_types": ["broiler", "layer"],
    },
    {
        "name": "Amo Farm Sieberer Hatchery",
        "state": "Oyo",
        "lga": "Ibarapa Central",
        "address": "Eruwa, Ibarapa, Oyo State",
        "phone": "0804-000-0003",
        "website": "https://amofarmsieberer.com",
        "bird_types": ["broiler", "layer"],
    },
    {
        "name": "CHI Farms Limited",
        "state": "Ogun",
        "lga": "Abeokuta South",
        "address": "Km 9, Abeokuta-Sagamu Road, Ogun State",
        "phone": "0805-000-0004",
        "website": "",
        "bird_types": ["broiler", "layer"],
    },
    {
        "name": "Obaseki Farms",
        "state": "Edo",
        "lga": "Oredo",
        "address": "Benin City, Edo State",
        "phone": "0806-000-0005",
        "website": "",
        "bird_types": ["broiler", "layer", "noiler"],
    },
    {
        "name": "Ekiti Farms",
        "state": "Ekiti",
        "lga": "Ado-Ekiti",
        "address": "Ado-Ekiti, Ekiti State",
        "phone": "0807-000-0006",
        "website": "",
        "bird_types": ["broiler", "layer"],
    },
    {
        "name": "Top-Feeds Hatchery Kano",
        "state": "Kano",
        "lga": "Kano Municipal",
        "address": "Bompai Industrial Layout, Kano",
        "phone": "0808-000-0007",
        "website": "",
        "bird_types": ["broiler", "layer"],
    },
    {
        "name": "Cadbury Nigeria Hatchery",
        "state": "Oyo",
        "lga": "Ibadan North",
        "address": "Apata, Ibadan, Oyo State",
        "phone": "0809-000-0008",
        "website": "",
        "bird_types": ["layer"],
    },
    {
        "name": "Naerls Poultry Farm",
        "state": "Kaduna",
        "lga": "Zaria",
        "address": "Ahmadu Bello University, Zaria, Kaduna State",
        "phone": "0810-000-0009",
        "website": "",
        "bird_types": ["broiler", "layer"],
    },
    {
        "name": "Hybrid Farms Hatchery",
        "state": "Lagos",
        "lga": "Alimosho",
        "address": "Egbeda, Alimosho, Lagos State",
        "phone": "0811-000-0010",
        "website": "",
        "bird_types": ["broiler", "layer"],
    },
    {
        "name": "Noiler Breed Farm",
        "state": "Ogun",
        "lga": "Abeokuta North",
        "address": "Abeokuta, Ogun State",
        "phone": "0812-000-0011",
        "website": "",
        "bird_types": ["noiler"],
    },
    {
        "name": "Leventis Technical Hatchery",
        "state": "Niger",
        "lga": "Bosso",
        "address": "Minna, Niger State",
        "phone": "0813-000-0012",
        "website": "",
        "bird_types": ["broiler", "layer"],
    },
    {
        "name": "Enugu State Poultry Farm",
        "state": "Enugu",
        "lga": "Enugu North",
        "address": "Independence Layout, Enugu",
        "phone": "0814-000-0013",
        "website": "",
        "bird_types": ["broiler", "layer"],
    },
    {
        "name": "Rivers State Agricultural Development Authority",
        "state": "Rivers",
        "lga": "Port Harcourt",
        "address": "Trans-Amadi, Port Harcourt, Rivers State",
        "phone": "0815-000-0014",
        "website": "",
        "bird_types": ["broiler", "layer"],
    },
    {
        "name": "BUA Group Hatchery",
        "state": "Kebbi",
        "lga": "Birnin Kebbi",
        "address": "Birnin Kebbi, Kebbi State",
        "phone": "0816-000-0015",
        "website": "",
        "bird_types": ["broiler"],
    },
    {
        "name": "Ogun State Farm Settlement Hatchery",
        "state": "Ogun",
        "lga": "Odogbolu",
        "address": "Ilaro Road, Odogbolu, Ogun State",
        "phone": "0817-000-0016",
        "website": "",
        "bird_types": ["broiler", "layer"],
    },
    {
        "name": "Delta Integrated Farm Centre",
        "state": "Delta",
        "lga": "Warri South",
        "address": "Warri, Delta State",
        "phone": "0818-000-0017",
        "website": "",
        "bird_types": ["broiler", "layer"],
    },
    {
        "name": "Abuja Hatchery (FCT)",
        "state": "FCT (Abuja)",
        "lga": "Gwagwalada",
        "address": "Gwagwalada, FCT Abuja",
        "phone": "0819-000-0018",
        "website": "",
        "bird_types": ["broiler", "layer"],
    },
]


class Command(BaseCommand):
    help = "Seed initial hatchery directory with known Nigerian DOC suppliers"

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Clear existing verified hatcheries before seeding",
        )

    def handle(self, *args, **kwargs):
        from apps.finance.market.models import Hatchery

        if kwargs["clear"]:
            deleted, _ = Hatchery.objects.filter(is_verified=True, added_by__isnull=True).delete()
            self.stdout.write(self.style.WARNING(f"Cleared {deleted} existing admin-seeded hatcheries."))

        created = 0
        skipped = 0
        for entry in SEED_DATA:
            _, was_created = Hatchery.objects.get_or_create(
                name=entry["name"],
                state=entry["state"],
                defaults={
                    "lga": entry["lga"],
                    "address": entry["address"],
                    "phone": entry["phone"],
                    "website": entry["website"],
                    "bird_types": entry["bird_types"],
                    "is_verified": True,
                    "added_by": None,
                },
            )
            if was_created:
                created += 1
            else:
                skipped += 1

        self.stdout.write(self.style.SUCCESS(
            f"Done! Created {created} hatcheries, skipped {skipped} duplicates.\n"
            f"Run: python manage.py seed_hatcheries"
        ))
