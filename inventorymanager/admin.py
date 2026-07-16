from django.contrib import admin
from .models import *


class CashTransactionAdmin(admin.ModelAdmin):
    fields = ("created_at",)
    list_display = ("created_at",)

admin.site.register(Supplier)
admin.site.register(Category)
admin.site.register(Customer)
admin.site.register(Product)
admin.site.register(Order)
admin.site.register(OrderItem)
admin.site.register(CashRegister)
admin.site.register(ActionLog)
admin.site.register(CashTransaction)
admin.site.register(OrderPayment)





