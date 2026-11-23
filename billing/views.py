import csv
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import CustomerForm, PaymentForm, ReadingForm
from .models import ZERO, AuditLog, Bill, Customer, Payment, Reading, role_of

ALL = ("admin", "billing", "accounts", "management")


def roles(*allowed):
    """Role-based access control: only the listed roles (and superusers) may open the view."""
    def decorator(view):
        @login_required
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if request.user.is_superuser or role_of(request.user) in allowed:
                return view(request, *args, **kwargs)
            messages.error(request, "You do not have permission to open that page.")
            return redirect("dashboard")
        return wrapper
    return decorator


def audit(request, action, detail=""):
    AuditLog.objects.create(user=request.user, action=action, detail=detail[:255])


def total(qs, field):
    return qs.aggregate(t=Sum(field))["t"] or ZERO


# ---------- Dashboard ----------
@roles(*ALL)
def dashboard(request):
    today = timezone.localdate()
    month = today.strftime("%Y-%m")
    billed, paid = total(Bill.objects, "total"), total(Payment.objects, "amount")
    ctx = {
        "customers": Customer.objects.filter(is_active=True).count(),
        "billed": billed, "paid": paid, "outstanding": billed - paid,
        "month_billed": total(Bill.objects.filter(period=month), "total"),
        "month_paid": total(Payment.objects.filter(paid_on__year=today.year, paid_on__month=today.month), "amount"),
        "unallocated": Payment.objects.filter(bill__isnull=True).count(),
        "overdue": Bill.objects.filter(status__in=["UNPAID", "PARTIAL"], due_date__lt=today).count(),
        "recent_bills": Bill.objects.select_related("customer")[:6],
        "recent_payments": Payment.objects.select_related("customer")[:6],
    }
    return render(request, "dashboard.html", ctx)


# ---------- Customers ----------
@roles(*ALL)
def customer_list(request):
    q = request.GET.get("q", "").strip()
    qs = Customer.objects.select_related("tariff")
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(account_number__icontains=q) |
                       Q(meter_number__icontains=q) | Q(phone__icontains=q))
    return render(request, "customer_list.html", {"customers": qs, "q": q})


@roles("admin", "billing")
def customer_create(request):
    form = CustomerForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        customer = form.save()
        audit(request, "Customer registered", f"{customer.account_number} {customer.name}")
        messages.success(request, f"Customer registered. Account number: {customer.account_number}")
        return redirect("customer_detail", pk=customer.pk)
    return render(request, "form.html", {"form": form, "title": "Register customer", "cancel": "/customers/"})


@roles("admin", "billing")
def customer_edit(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    form = CustomerForm(request.POST or None, instance=customer)
    if request.method == "POST" and form.is_valid():
        form.save()
        audit(request, "Customer updated", f"{customer.account_number} {customer.name}")
        messages.success(request, "Customer details updated.")
        return redirect("customer_detail", pk=pk)
    return render(request, "form.html", {"form": form, "title": f"Edit {customer.name}", "cancel": f"/customers/{pk}/"})


@roles(*ALL)
def customer_detail(request, pk):
    customer = get_object_or_404(Customer.objects.select_related("tariff"), pk=pk)
    return render(request, "customer_detail.html", {
        "c": customer,
        "bills": customer.bills.all(),
        "payments": customer.payments.select_related("bill"),
    })


# ---------- Meter readings & bills ----------
@roles(*ALL)
def reading_list(request):
    return render(request, "reading_list.html", {"readings": Reading.objects.select_related("customer")[:300]})


@roles("admin", "billing")
def reading_create(request):
    form = ReadingForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            reading = form.save(commit=False)
            reading.recorded_by = request.user
            reading.save()
            bill = Bill.generate(reading)
        audit(request, "Bill generated", f"{bill.number} {bill.customer.account_number} total {bill.total}")
        messages.success(request, f"Reading saved and bill {bill.number} generated.")
        return redirect("bill_detail", pk=bill.pk)
    return render(request, "reading_form.html", {"form": form, "title": "Record meter reading", "cancel": "/readings/"})


@roles(*ALL)
def bill_list(request):
    q, status = request.GET.get("q", "").strip(), request.GET.get("status", "")
    qs = Bill.objects.select_related("customer")
    if q:
        qs = qs.filter(Q(number__icontains=q) | Q(customer__name__icontains=q) | Q(customer__account_number__icontains=q))
    if status:
        qs = qs.filter(status=status)
    return render(request, "bill_list.html", {"bills": qs[:300], "q": q, "status": status, "statuses": Bill.STATUS})


@roles(*ALL)
def bill_detail(request, pk):
    bill = get_object_or_404(Bill.objects.select_related("customer", "customer__tariff", "reading"), pk=pk)
    return render(request, "bill_detail.html", {"b": bill, "payments": bill.payments.all()})


# ---------- Payments ----------
@roles(*ALL)
def payment_list(request):
    return render(request, "payment_list.html", {"payments": Payment.objects.select_related("customer", "bill")[:300]})


@roles("admin", "accounts")
def payment_create(request):
    initial = {"paid_on": timezone.localdate(), "customer": request.GET.get("customer")}
    form = PaymentForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            payment = form.save(commit=False)
            payment.recorded_by = request.user
            if not payment.bill:  # auto-link to the customer's oldest unpaid bill
                payment.bill = (Bill.objects.filter(customer=payment.customer, status__in=["UNPAID", "PARTIAL"])
                                .order_by("issue_date", "id").first())
            payment.save()
        audit(request, "Payment recorded", f"{payment.reference} {payment.customer.account_number} KES {payment.amount}")
        if payment.bill:
            messages.success(request, f"Payment recorded and applied to bill {payment.bill.number} ({payment.bill.get_status_display()}).")
        else:
            messages.warning(request, "Payment recorded, but the customer has no open bill. It is held as unallocated for reconciliation.")
        return redirect("payment_list")
    return render(request, "payment_form.html", {"form": form, "title": "Record payment", "cancel": "/payments/"})


# ---------- Reconciliation ----------
@roles("admin", "accounts", "management")
def reconciliation(request):
    if request.method == "POST":
        if role_of(request.user) not in ("admin", "accounts"):
            messages.error(request, "Only accounts staff can resolve discrepancies.")
            return redirect("reconciliation")
        payment = get_object_or_404(Payment, pk=request.POST.get("payment"))
        bill = get_object_or_404(Bill, pk=request.POST.get("bill"))
        if bill.customer_id != payment.customer_id:
            messages.error(request, "That bill belongs to a different customer.")
        else:
            payment.allocate(bill)
            audit(request, "Payment reconciled", f"{payment.reference} linked to {bill.number}")
            messages.success(request, f"Payment {payment.reference} linked to bill {bill.number}.")
        return redirect("reconciliation")

    today = timezone.localdate()
    unallocated = [{"p": p, "bills": Bill.objects.filter(customer=p.customer).exclude(status="PAID")}
                   for p in Payment.objects.filter(bill__isnull=True).select_related("customer")]
    billed, paid = total(Bill.objects, "total"), total(Payment.objects, "amount")
    ctx = {
        "unallocated": unallocated,
        "overpaid": Bill.objects.filter(status="OVERPAID").select_related("customer"),
        "overdue": Bill.objects.filter(status__in=["UNPAID", "PARTIAL"], due_date__lt=today).select_related("customer"),
        "billed": billed, "paid": paid, "outstanding": billed - paid,
        "unallocated_total": total(Payment.objects.filter(bill__isnull=True), "amount"),
        "can_resolve": role_of(request.user) in ("admin", "accounts"),
    }
    return render(request, "reconcile.html", ctx)


# ---------- Reports & audit ----------
@roles(*ALL)
def reports(request):
    return render(request, "reports.html", {
        "by_status": Bill.objects.values("status").annotate(n=Count("id"), t=Sum("total")).order_by("status"),
        "by_method": Payment.objects.values("method").annotate(n=Count("id"), t=Sum("amount")).order_by("method"),
        "top_debtors": sorted(Customer.objects.all(), key=lambda c: c.balance, reverse=True)[:10],
    })


@roles(*ALL)
def export_bills(request):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="bills.csv"'
    writer = csv.writer(response)
    writer.writerow(["Bill", "Account", "Customer", "Period", "Units", "Total", "Paid", "Balance", "Status", "Due date"])
    for b in Bill.objects.select_related("customer"):
        writer.writerow([b.number, b.customer.account_number, b.customer.name, b.period, b.units,
                         b.total, b.paid, b.balance, b.status, b.due_date])
    return response


@roles(*ALL)
def export_payments(request):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="payments.csv"'
    writer = csv.writer(response)
    writer.writerow(["Reference", "Account", "Customer", "Amount", "Method", "Date", "Applied to bill"])
    for p in Payment.objects.select_related("customer", "bill"):
        writer.writerow([p.reference, p.customer.account_number, p.customer.name, p.amount, p.method,
                         p.paid_on, p.bill.number if p.bill else "UNALLOCATED"])
    return response


@roles("admin", "management")
def audit_log(request):
    return render(request, "audit.html", {"logs": AuditLog.objects.select_related("user")[:300]})


# ---------- JSON helpers used by the JavaScript ----------
@roles(*ALL)
def customer_info(request, pk):
    c = get_object_or_404(Customer.objects.select_related("tariff"), pk=pk)
    last = c.readings.order_by("-period").first()
    return JsonResponse({
        "name": c.name, "meter": c.meter_number, "rate": float(c.tariff.rate_per_unit),
        "fixed": float(c.tariff.fixed_charge), "vat": float(c.tariff.vat_percent),
        "has_previous": bool(last), "previous": str(last.current_reading) if last else "0.00",
        "last_period": last.period if last else "",
    })


@roles(*ALL)
def open_bills(request, pk):
    bills = Bill.objects.filter(customer_id=pk).exclude(status="PAID").order_by("issue_date", "id")
    return JsonResponse([{"id": b.pk, "label": f"{b.number} | {b.period} | balance KES {b.balance:.2f}"} for b in bills], safe=False)
