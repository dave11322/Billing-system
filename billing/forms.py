from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import Bill, Customer, Payment, Reading


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ["name", "phone", "email", "address", "meter_number", "tariff", "is_active"]

    def clean_meter_number(self):
        return self.cleaned_data["meter_number"].strip().upper()


class ReadingForm(forms.ModelForm):
    previous_reading = forms.DecimalField(
        required=False, max_digits=12, decimal_places=2, min_value=0,
        help_text="Filled automatically from the last reading. Only enter it for a customer's first reading.")

    class Meta:
        model = Reading
        fields = ["customer", "period", "previous_reading", "current_reading"]
        widgets = {"period": forms.TextInput(attrs={"type": "month"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["customer"].queryset = Customer.objects.filter(is_active=True)
        self.fields["period"].initial = timezone.localdate().strftime("%Y-%m")

    def clean(self):
        data = super().clean()
        customer, current, period = data.get("customer"), data.get("current_reading"), data.get("period")
        if not customer or current is None:
            return data
        last = customer.readings.order_by("-period").first()
        if last:
            previous = last.current_reading  # always trust the stored last reading
            if period and period <= last.period:
                raise ValidationError(
                    f"A reading for {last.period} already exists. The new billing month must be later than that.")
        else:
            previous = data.get("previous_reading") or Decimal("0.00")
        data["previous_reading"] = previous
        if current < previous:
            raise ValidationError(f"Current reading ({current}) cannot be lower than the previous reading ({previous}).")
        return data


class PaymentForm(forms.ModelForm):
    bill = forms.ModelChoiceField(
        queryset=Bill.objects.none(), required=False,
        empty_label="— Auto-apply to oldest unpaid bill —")

    class Meta:
        model = Payment
        fields = ["customer", "bill", "amount", "method", "reference", "paid_on"]
        widgets = {"paid_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["customer"].queryset = Customer.objects.filter(is_active=True)
        if self.is_bound:
            self.fields["bill"].queryset = Bill.objects.all()

    def clean_reference(self):
        return self.cleaned_data["reference"].strip().upper()

    def clean_paid_on(self):
        date = self.cleaned_data["paid_on"]
        if date > timezone.localdate():
            raise ValidationError("Payment date cannot be in the future.")
        return date
