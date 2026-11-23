from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from billing.models import Bill, Customer, Payment, Profile, Reading, Tariff

User = get_user_model()


class Command(BaseCommand):
    help = "Create demo tariffs, users, customers, readings, bills and payments."

    @transaction.atomic
    def handle(self, *args, **options):
        if Customer.objects.exists():
            self.stdout.write("Demo data already exists. Skipping.")
            return

        domestic = Tariff.objects.create(name="Domestic", rate_per_unit=Decimal("25.00"), fixed_charge=Decimal("150.00"))
        commercial = Tariff.objects.create(name="Commercial", rate_per_unit=Decimal("22.00"), fixed_charge=Decimal("500.00"))

        admin = User.objects.create_superuser("admin", "admin@example.com", "Admin@12345")
        users = {}
        for username, role in [("billing1", "billing"), ("accounts1", "accounts"), ("manager1", "management")]:
            u = User.objects.create_user(username, password="Pass@12345")
            Profile.objects.filter(user=u).update(role=role)
            users[role] = u

        names = ["Wanjiku Mwangi", "Otieno Odhiambo", "Amina Hassan", "Kamau Njoroge",
                 "Achieng Atieno", "Mutua Kioko", "Chebet Kiprop", "Mwende Muthoni"]
        customers = []
        for i, name in enumerate(names, start=1):
            customers.append(Customer.objects.create(
                name=name, phone=f"07120000{i:02d}", address=f"Plot {i}, Nairobi",
                meter_number=f"MTR{1000 + i}", tariff=commercial if i in (4, 8) else domestic))

        today = timezone.localdate()
        last_month = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
        bills = []
        for i, c in enumerate(customers, start=1):
            reading = Reading.objects.create(customer=c, period=last_month, previous_reading=Decimal("100.00"),
                                             current_reading=Decimal(100 + 40 + i * 13), recorded_by=users["billing"])
            bills.append(Bill.generate(reading))

        def pay(i, amount, ref, bill=True):
            Payment.objects.create(customer=customers[i], bill=bills[i] if bill else None, amount=Decimal(amount),
                                   method="MPESA", reference=ref, paid_on=today, recorded_by=users["accounts"])

        pay(0, bills[0].total, "QWE1001")                         # paid in full
        pay(1, (bills[1].total / 2).quantize(Decimal("0.01")), "QWE1002")  # partial
        pay(2, bills[2].total + Decimal("500.00"), "QWE1003")     # overpaid -> discrepancy
        pay(3, "1000.00", "QWE1004", bill=False)                  # unallocated -> reconcile
        for b in bills:
            b.refresh_status()
        self.stdout.write(self.style.SUCCESS("Demo data created."))
        self.stdout.write("Logins -> admin / Admin@12345 | billing1, accounts1, manager1 / Pass@12345")
