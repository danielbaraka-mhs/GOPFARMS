from decimal import Decimal

from django.conf import settings
from django.db import models


class Product(models.Model):
    CATEGORY_VEGETABLES = "Vegetables"
    CATEGORY_FRUITS = "Fruits"
    CATEGORY_GRAINS = "Grains & Cereals"
    CATEGORY_SEEDS = "Seeds & Seedlings"
    CATEGORY_LIVESTOCK = "Livestock & Poultry"
    CATEGORY_FERTILIZER = "Fertilizer & Soil"
    CATEGORY_EQUIPMENT = "Farm Equipment"

    CATEGORY_CHOICES = [
        (CATEGORY_VEGETABLES, CATEGORY_VEGETABLES),
        (CATEGORY_FRUITS, CATEGORY_FRUITS),
        (CATEGORY_GRAINS, CATEGORY_GRAINS),
        (CATEGORY_SEEDS, CATEGORY_SEEDS),
        (CATEGORY_LIVESTOCK, CATEGORY_LIVESTOCK),
        (CATEGORY_FERTILIZER, CATEGORY_FERTILIZER),
        (CATEGORY_EQUIPMENT, CATEGORY_EQUIPMENT),
    ]

    seller = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="products")
    title = models.CharField(max_length=200)
    category = models.CharField(max_length=32, choices=CATEGORY_CHOICES, default=CATEGORY_VEGETABLES)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    unit = models.CharField(max_length=50, default="unit")
    quantity = models.PositiveIntegerField(default=0)
    sold = models.PositiveIntegerField(default=0)
    description = models.TextField(blank=True)
    location = models.CharField(max_length=120, blank=True)
    image_url = models.URLField(blank=True)
    date_added = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-date_added", "title"]

    def __str__(self):
        return self.title

    @property
    def emoji(self):
        return {
            self.CATEGORY_VEGETABLES: "🥕",
            self.CATEGORY_FRUITS: "🍅",
            self.CATEGORY_GRAINS: "🌽",
            self.CATEGORY_SEEDS: "🌱",
            self.CATEGORY_LIVESTOCK: "🐓",
            self.CATEGORY_FERTILIZER: "🪴",
            self.CATEGORY_EQUIPMENT: "🚜",
        }.get(self.category, "🌿")

    @property
    def display_date(self):
        return self.date_added.strftime("%b %d")


class Order(models.Model):
    STATUS_PENDING = "Pending"
    STATUS_SHIPPED = "Shipped"
    STATUS_DELIVERED = "Delivered"

    STATUS_CHOICES = [
        (STATUS_PENDING, STATUS_PENDING),
        (STATUS_SHIPPED, STATUS_SHIPPED),
        (STATUS_DELIVERED, STATUS_DELIVERED),
    ]

    order_number = models.CharField(max_length=48, unique=True)
    item_name = models.CharField(max_length=200)
    customer_name = models.CharField(max_length=120)
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    product = models.ForeignKey(Product, null=True, blank=True, on_delete=models.SET_NULL, related_name="orders")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.order_number
