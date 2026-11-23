from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path("login/", auth_views.LoginView.as_view(template_name="login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", views.dashboard, name="dashboard"),
    path("customers/", views.customer_list, name="customer_list"),
    path("customers/new/", views.customer_create, name="customer_create"),
    path("customers/<int:pk>/", views.customer_detail, name="customer_detail"),
    path("customers/<int:pk>/edit/", views.customer_edit, name="customer_edit"),
    path("readings/", views.reading_list, name="reading_list"),
    path("readings/new/", views.reading_create, name="reading_create"),
    path("bills/", views.bill_list, name="bill_list"),
    path("bills/<int:pk>/", views.bill_detail, name="bill_detail"),
    path("payments/", views.payment_list, name="payment_list"),
    path("payments/new/", views.payment_create, name="payment_create"),
    path("reconciliation/", views.reconciliation, name="reconciliation"),
    path("reports/", views.reports, name="reports"),
    path("reports/bills.csv", views.export_bills, name="export_bills"),
    path("reports/payments.csv", views.export_payments, name="export_payments"),
    path("audit/", views.audit_log, name="audit_log"),
    path("api/customers/<int:pk>/info/", views.customer_info, name="customer_info"),
    path("api/customers/<int:pk>/open-bills/", views.open_bills, name="open_bills"),
]
