from django.contrib import admin

from .models import AuditLog, Bill, Customer, Payment, Profile, Reading, Tariff


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role")
    list_editable = ("role",)


admin.site.register(Tariff)
admin.site.register(Customer)
admin.site.register(Reading)
admin.site.register(Bill)
admin.site.register(Payment)


@admin.register(AuditLog)
class AuditAdmin(admin.ModelAdmin):
    list_display = ("created", "user", "action", "detail")
    readonly_fields = ("user", "action", "detail", "created")
