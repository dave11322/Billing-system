from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Sum
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

ZERO = Decimal("0.00")
CENT = Decimal("0.01")
PERIOD_VALIDATOR = RegexValidator(r"^\d{4}-(0[1-9]|1[0-2])$", "Use the format YYYY-MM, e.g. 2026-11.")


# ---------- Users & roles (role-based access) ----------
class Profile(models.Model):
    ROLES = [
        ("admin", "System Administrator"),
        ("billing", "Billing Staff"),
        ("accounts", "Accounts / Finance Staff"),
        ("management", "Management"),
    ]
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=ROLES, default="billing")

    def __str__(self):
        return f"{self.user.username} ({self.get_role_display()})"


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance, role="admin" if instance.is_superuser else "billing")


def role_of(user):
    if user.is_superuser:
        return "admin"
    profile, _ = Profile.objects.get_or_create(user=user)
    return profile.role


# ---------- Core billing data ----------
class Tariff(models.Model):
    name = models.CharField(max_length=60, unique=True)
    rate_per_unit = models.DecimalField("Rate per unit (kWh)", max_digits=8, decimal_places=2,
                                        validators=[MinValueValidator(Decimal("0.01"))])
    fixed_charge = models.DecimalField("Fixed monthly charge", max_digits=10, decimal_places=2, default=ZERO)
    vat_percent = models.DecimalField("VAT %", max_digits=5, decimal_places=2, default=Decimal("16.00"))

    def __str__(self):
        return f"{self.name} (KES {self.rate_per_unit}/unit)"


class Customer(models.Model):
    account_number = models.CharField(max_length=20, unique=True, null=True, editable=False)
    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=200)
    meter_number = models.CharField(max_length=30, unique=True)
    tariff = models.ForeignKey(Tariff, on_delete=models.PROTECT)
    is_active = models.BooleanField(default=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.account_number:
            self.account_number = f"ACC{self.pk:05d}"
            super().save(update_fields=["account_number"])

    @property
    def total_billed(self):
        return self.bills.aggregate(t=Sum("total"))["t"] or ZERO

    @property
    def total_paid(self):
        return self.payments.aggregate(t=Sum("amount"))["t"] or ZERO

    @property
    def balance(self):
        """Positive = customer owes money. Negative = customer is in credit."""
        return self.total_billed - self.total_paid

    def __str__(self):
        return f"{self.account_number} - {self.name}"


class Reading(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="readings")
    period = models.CharField("Billing month", max_length=7, validators=[PERIOD_VALIDATOR])
    previous_reading = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(ZERO)])
    current_reading = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(ZERO)])
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-period", "-id"]
        constraints = [models.UniqueConstraint(fields=["customer", "period"], name="one_reading_per_month")]

    @property
    def units(self):
        return self.current_reading - self.previous_reading

    def clean(self):
        if self.current_reading is not None and self.previous_reading is not None \
                and self.current_reading < self.previous_reading:
            raise ValidationError("Current reading cannot be lower than the previous reading.")

    def __str__(self):
        return f"{self.customer.account_number} {self.period}"


class Bill(models.Model):
    STATUS = [("UNPAID", "Unpaid"), ("PARTIAL", "Partially paid"), ("PAID", "Paid"), ("OVERPAID", "Overpaid")]
    number = models.CharField(max_length=25, unique=True, null=True, editable=False)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="bills")
    reading = models.OneToOneField(Reading, on_delete=models.PROTECT)
    period = models.CharField(max_length=7)
    units = models.DecimalField(max_digits=12, decimal_places=2)
    rate = models.DecimalField(max_digits=8, decimal_places=2)
    energy_charge = models.DecimalField(max_digits=12, decimal_places=2)
    fixed_charge = models.DecimalField(max_digits=12, decimal_places=2)
    vat = models.DecimalField(max_digits=12, decimal_places=2)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    issue_date = models.DateField()
    due_date = models.DateField()
    status = models.CharField(max_length=10, choices=STATUS, default="UNPAID")

    class Meta:
        ordering = ["-issue_date", "-id"]

    @classmethod
    def generate(cls, reading):
        """Single place where bills are calculated, so every bill uses the same rules."""
        customer, tariff = reading.customer, reading.customer.tariff
        units = reading.units
        energy = (units * tariff.rate_per_unit).quantize(CENT)
        fixed = tariff.fixed_charge
        vat = ((energy + fixed) * tariff.vat_percent / Decimal("100")).quantize(CENT)
        today = timezone.localdate()
        bill = cls.objects.create(
            customer=customer, reading=reading, period=reading.period, units=units,
            rate=tariff.rate_per_unit, energy_charge=energy, fixed_charge=fixed, vat=vat,
            total=energy + fixed + vat, issue_date=today, due_date=today + timedelta(days=14),
        )
        bill.number = f"INV-{reading.period.replace('-', '')}-{bill.pk:05d}"
        bill.save(update_fields=["number"])
        return bill

    @property
    def paid(self):
        return self.payments.aggregate(t=Sum("amount"))["t"] or ZERO

    @property
    def balance(self):
        return self.total - self.paid

    @property
    def is_overdue(self):
        return self.status in ("UNPAID", "PARTIAL") and self.due_date < timezone.localdate()

    def refresh_status(self):
        paid = self.paid
        if paid <= 0:
            status = "UNPAID"
        elif paid < self.total:
            status = "PARTIAL"
        elif paid == self.total:
            status = "PAID"
        else:
            status = "OVERPAID"
        if status != self.status:
            self.status = status
            self.save(update_fields=["status"])

    def __str__(self):
        return self.number or f"Bill {self.pk}"


class Payment(models.Model):
    METHODS = [("MPESA", "M-Pesa"), ("BANK", "Bank transfer"), ("CASH", "Cash"), ("CHEQUE", "Cheque")]
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="payments")
    bill = models.ForeignKey(Bill, null=True, blank=True, on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    method = models.CharField(max_length=10, choices=METHODS)
    reference = models.CharField("Transaction reference", max_length=40, unique=True,
                                 help_text="M-Pesa code, bank slip or receipt number. Must be unique.")
    paid_on = models.DateField()
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-paid_on", "-id"]

    def clean(self):
        if self.bill_id and self.customer_id and self.bill.customer_id != self.customer_id:
            raise ValidationError("The selected bill belongs to a different customer.")

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.bill_id:
            self.bill.refresh_status()

    def allocate(self, bill):
        old = self.bill
        self.bill = bill
        self.save(update_fields=["bill"])
        if old:
            old.refresh_status()

    def __str__(self):
        return f"{self.reference} - {self.amount}"


# ---------- Audit trail ----------
class AuditLog(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=60)
    detail = models.CharField(max_length=255, blank=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created", "-id"]

    def __str__(self):
        return f"{self.created:%Y-%m-%d %H:%M} {self.action}"
