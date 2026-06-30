from decimal import Decimal
from django.contrib.auth import get_user_model
from django.shortcuts import render

from .models import Order, Product

User = get_user_model()

DEFAULT_PRODUCT_IMAGE = "https://images.unsplash.com/photo-1500937386664-56d1dfef3854?w=600&q=80"


def get_demo_user():
    demo_user, created = User.objects.get_or_create(
        username="demo_seller",
        defaults={
            "email": "demo_seller@example.com",
            "first_name": "Harper",
            "last_name": "Kim",
        },
    )
    if created:
        demo_user.set_unusable_password()
        demo_user.save()
    return demo_user


def seed_demo_data():
    if Product.objects.exists() and Order.objects.exists():
        return

    demo_user = get_demo_user()

    if not Product.objects.exists():
        demo_products = [
            {
                "title": "Fresh Roma Tomatoes",
                "category": Product.CATEGORY_VEGETABLES,
                "price": Decimal("2.50"),
                "unit": "kg",
                "quantity": 120,
                "sold": 340,
                "description": "Vine-ripened Roma tomatoes, harvested this morning. Great for sauces and salads.",
                "location": "Lilongwe, Central Region",
                "image_url": "https://images.unsplash.com/photo-1546470427-e26264be0b0d?w=600&q=80",
            },
            {
                "title": "Organic Maize (Yellow)",
                "category": Product.CATEGORY_GRAINS,
                "price": Decimal("18.00"),
                "unit": "bag",
                "quantity": 40,
                "sold": 58,
                "description": "Sun-dried organic yellow maize, properly winnowed and bagged. Bulk discounts available.",
                "location": "Kasungu District",
                "image_url": "https://images.unsplash.com/photo-1601593768799-76e0f5a78aaf?w=600&q=80",
            },
            {
                "title": "Hass Avocados",
                "category": Product.CATEGORY_FRUITS,
                "price": Decimal("4.00"),
                "unit": "dozen",
                "quantity": 60,
                "sold": 95,
                "description": "Creamy Hass avocados from shaded hillside orchards. Ready to eat in 2-3 days.",
                "location": "Mulanje, Southern Region",
                "image_url": "https://images.unsplash.com/photo-1523049673857-eb18f1d7b578?w=600&q=80",
            },
            {
                "title": "Hybrid Tomato Seedlings",
                "category": Product.CATEGORY_SEEDS,
                "price": Decimal("0.35"),
                "unit": "unit",
                "quantity": 500,
                "sold": 1200,
                "description": "Disease-resistant hybrid tomato seedlings, 4 weeks old, ready for transplant.",
                "location": "Zomba, Southern Region",
                "image_url": "https://images.unsplash.com/photo-1524594152303-9fd13543fe6e?w=600&q=80",
            },
            {
                "title": "Free-Range Layer Hens",
                "category": Product.CATEGORY_LIVESTOCK,
                "price": Decimal("12.00"),
                "unit": "head",
                "quantity": 25,
                "sold": 41,
                "description": "18-week-old free-range layer hens, vaccinated and in lay. Healthy stock.",
                "location": "Salima, Central Region",
                "image_url": "https://images.unsplash.com/photo-1612170153139-6f881ff067e0?w=600&q=80",
            },
            {
                "title": "Composted Organic Manure",
                "category": Product.CATEGORY_FERTILIZER,
                "price": Decimal("9.00"),
                "unit": "bag",
                "quantity": 80,
                "sold": 64,
                "description": "Fully composted organic manure, weed-seed free, rich in nitrogen. 50kg bags.",
                "location": "Blantyre, Southern Region",
                "image_url": "https://images.unsplash.com/photo-1582281298055-e25b84a30b0b?w=600&q=80",
            },
            {
                "title": "Hand Push Seeder",
                "category": Product.CATEGORY_EQUIPMENT,
                "price": Decimal("65.00"),
                "unit": "unit",
                "quantity": 6,
                "sold": 9,
                "description": "Lightly used manual push seeder for row crops. Adjustable seed spacing.",
                "location": "Lilongwe, Central Region",
                "image_url": "https://images.unsplash.com/photo-1591857177580-dc82b9ac4e1e?w=600&q=80",
            },
        ]

        Product.objects.bulk_create([
            Product(seller=demo_user, **product) for product in demo_products
        ])

    if not Order.objects.exists():
        demo_products = list(Product.objects.all()[:4])
        demo_orders = [
            {
                "order_number": "TCK-458291",
                "item_name": "Strawberries",
                "customer_name": "Emma L.",
                "amount": Decimal("24.50"),
                "status": Order.STATUS_PENDING,
                "product": demo_products[0] if demo_products else None,
            },
            {
                "order_number": "TCK-458292",
                "item_name": "Apples",
                "customer_name": "Noah J.",
                "amount": Decimal("16.20"),
                "status": Order.STATUS_SHIPPED,
                "product": demo_products[1] if len(demo_products) > 1 else None,
            },
            {
                "order_number": "TCK-458293",
                "item_name": "Carrots",
                "customer_name": "Ava M.",
                "amount": Decimal("12.30"),
                "status": Order.STATUS_DELIVERED,
                "product": demo_products[2] if len(demo_products) > 2 else None,
            },
            {
                "order_number": "TCK-458294",
                "item_name": "Hybrid Tomato Seedlings",
                "customer_name": "Liam S.",
                "amount": Decimal("18.90"),
                "status": Order.STATUS_PENDING,
                "product": demo_products[3] if len(demo_products) > 3 else None,
            },
        ]

        Order.objects.bulk_create([Order(**order) for order in demo_orders])


def serialize_product(product):
    return {
        "id": product.id,
        "title": product.title,
        "category": product.category,
        "emoji": product.emoji,
        "price": float(product.price),
        "unit": product.unit,
        "qty": product.quantity,
        "sold": product.sold,
        "location": product.location,
        "seller": product.seller.get_full_name() or product.seller.username,
        "desc": product.description,
        "img": product.image_url or DEFAULT_PRODUCT_IMAGE,
        "date": product.display_date,
    }


def serialize_order(order):
    return {
        "id": order.order_number,
        "item": order.item_name,
        "amount": float(order.amount),
    }


def home(request):
    return render(request, "farms/index.html")


def categories(request):
    return render(request, "farms/categories.html")


def dashboard(request):
    seed_demo_data()
    total_orders = Order.objects.count()
    total_products = Product.objects.count()
    total_revenue = sum((product.price * product.sold for product in Product.objects.all()), Decimal("0.00"))
    stats = {
        "orders": total_orders,
        "products": total_products,
        "revenue": float(total_revenue),
    }
    recent = [serialize_order(order) for order in Order.objects.order_by("-created_at")[:3]]
    return render(request, "farms/dashboard.html", {"stats": stats, "recent": recent})


def dashboard_seller(request):
    seed_demo_data()
    seller = request.user if request.user.is_authenticated else get_demo_user()
    all_products = Product.objects.filter(is_active=True)
    user_products = all_products.filter(seller=seller)
    products = [serialize_product(product) for product in all_products]
    user_products_data = [serialize_product(product) for product in user_products]
    next_id = max((product.id for product in all_products), default=0) + 1

    seller_name = seller.get_full_name() or seller.username
    initials = "".join([part[:1].upper() for part in seller_name.split()][:2]) or "HK"
    context = {
        "products": products,
        "user_products": user_products_data,
        "next_id": next_id,
        "seller_name": seller_name,
        "seller_initials": initials,
        "seller_location": "Lilongwe, Central Region",
        "member_since": seller.date_joined.strftime("%b %Y") if getattr(seller, 'date_joined', None) else "Jan 2024",
    }
    return render(request, "farms/dashboard_seller.html", context)


def trackoder(request):
    """Render the TrackOrder (trackoder) design with sample order/tracking data."""
    order = {
        "id": "TCK-458291",
        "status": "In Transit",
        "progress": 65,
        "placed": "2026-06-20",
        "eta": "2026-06-26",
    }
    steps = [
        {"label": "Order Placed", "done": True, "time": "2026-06-20 09:12"},
        {"label": "Packed", "done": True, "time": "2026-06-21 11:00"},
        {"label": "Shipped", "done": True, "time": "2026-06-22 08:30"},
        {"label": "In Transit", "done": False, "time": ""},
        {"label": "Out for delivery", "done": False, "time": ""},
    ]
    return render(request, "farms/trackoder.html", {"order": order, "steps": steps})
