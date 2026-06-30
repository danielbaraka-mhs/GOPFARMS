from django.contrib import admin

from .models import Order, Product


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("title", "seller", "category", "price", "quantity", "sold", "is_active")
    list_filter = ("category", "is_active")
    search_fields = ("title", "description", "location", "seller__username")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("order_number", "item_name", "customer_name", "amount", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("order_number", "item_name", "customer_name")
