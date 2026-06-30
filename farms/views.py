from django.shortcuts import render


def home(request):
    return render(request, "farms/index.html")


def categories(request):
    return render(request, "farms/categories.html")


def dashboard(request):
    """Simple dashboard view with example stats for the new dashboard design."""
    stats = {
        "orders": 124,
        "products": 58,
        "revenue": 12450,
    }
    recent = [
        {"id": 1001, "item": "Strawberries", "amount": 4.99},
        {"id": 1002, "item": "Apples", "amount": 2.49},
        {"id": 1003, "item": "Carrots", "amount": 1.49},
    ]
    return render(request, "farms/dashboard.html", {"stats": stats, "recent": recent})


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
