import mimetypes
import os
import uuid
from decimal import Decimal
from typing import List, Optional

import schemas
from database import supabase_client, PRODUCT_IMAGES_BUCKET
from passlib.context import CryptContext

if not supabase_client:
    raise RuntimeError(
        "Supabase client is not configured. Set SUPABASE_URL and SUPABASE_ANON_KEY/SUPABASE_SERVICE_ROLE_KEY."
    )


def _row_to_profile(row: dict) -> schemas.UserProfileRead:
    return schemas.UserProfileRead.model_validate(row)


def _row_to_user(row: dict) -> schemas.UserRead:
    profile_row = _fetch_profile_for_user(row.get("id"))
    profile = _row_to_profile(profile_row) if profile_row else None
    return schemas.UserRead.model_validate({**row, "profile": profile})


def _row_to_product(row: dict) -> schemas.ProductRead:
    return schemas.ProductRead.model_validate(
        {**row, "date_added": row.get("created_at")}
    )


def _row_to_order(row: dict) -> schemas.OrderRead:
    return schemas.OrderRead.model_validate(row)


def _fetch_profile_for_user(user_id: int) -> Optional[dict]:
    response = (
        supabase_client.table("user_profiles")
        .select("*")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    records = response.data or []
    return records[0] if records else None


def get_display_name(user: schemas.UserRead) -> str:
    return (
        " ".join(filter(None, [user.first_name or "", user.last_name or ""]))
        or user.username
    )


def get_user_by_email(db, email: str) -> Optional[schemas.UserRead]:
    response = (
        supabase_client.table("users").select("*").eq("email", email).limit(1).execute()
    )
    records = response.data or []
    return _row_to_user(records[0]) if records else None


def get_user(db, user_id: int) -> Optional[schemas.UserRead]:
    response = (
        supabase_client.table("users").select("*").eq("id", user_id).limit(1).execute()
    )
    records = response.data or []
    return _row_to_user(records[0]) if records else None


def get_users(db) -> List[schemas.UserRead]:
    response = (
        supabase_client.table("users")
        .select("*")
        .order("created_at", desc=True)
        .execute()
    )
    return [_row_to_user(row) for row in (response.data or [])]


def _ensure_profile(user_id: int) -> None:
    if _fetch_profile_for_user(user_id):
        return
    supabase_client.table("user_profiles").insert({"user_id": user_id}).execute()


def create_user_if_missing(
    db, email: str, first_name: str, last_name: str
) -> schemas.UserRead:
    existing = get_user_by_email(db, email)
    if existing:
        return existing

    username = email.split("@")[0]
    payload = {
        "username": username,
        "email": email,
        "first_name": first_name,
        "last_name": last_name,
        "is_active": True,
        "account_type": "customer",
    }
    response = supabase_client.table("users").insert(payload).select("*").execute()
    user_row = response.data[0]
    _ensure_profile(user_row["id"])
    return _row_to_user(user_row)


def create_demo_user(db) -> schemas.UserRead:
    demo_email = "demo_seller@example.com"
    existing = get_user_by_email(db, demo_email)
    if existing:
        return existing

    response = (
        supabase_client.table("users")
        .insert(
            {
                "username": "demo_seller",
                "email": demo_email,
                "first_name": "Harper",
                "last_name": "Kim",
                "is_active": True,
                "account_type": "seller",
            }
        )
        .select("*")
        .execute()
    )
    user_row = response.data[0]
    _ensure_profile(user_row["id"])
    return _row_to_user(user_row)


def seed_demo_data(db) -> None:
    # Optional helper used by seller dashboard.
    # No-op by default if demo data is not required.
    return


def create_user_profile_if_missing(
    db, user: schemas.UserRead
) -> schemas.UserProfileRead:
    profile_row = _fetch_profile_for_user(user.id)
    if profile_row:
        return _row_to_profile(profile_row)
    response = (
        supabase_client.table("user_profiles")
        .insert({"user_id": user.id})
        .select("*")
        .execute()
    )
    return _row_to_profile(response.data[0])


def update_user(
    db,
    user: schemas.UserRead,
    email: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    account_type: Optional[str] = None,
) -> schemas.UserRead:
    updates = {}
    if email is not None:
        updates["email"] = email
    if first_name is not None:
        updates["first_name"] = first_name
    if last_name is not None:
        updates["last_name"] = last_name
    if account_type is not None:
        updates["account_type"] = account_type
    if not updates:
        return user
    response = (
        supabase_client.table("users")
        .update(updates)
        .eq("id", user.id)
        .select("*")
        .execute()
    )
    return _row_to_user(response.data[0])


def update_user_profile(
    db, user: schemas.UserRead, profile_data: schemas.UserProfileBase
) -> schemas.UserProfileRead:
    profile = create_user_profile_if_missing(db, user)
    updates = {k: v for k, v in profile_data.model_dump().items() if v is not None}
    response = (
        supabase_client.table("user_profiles")
        .update(updates)
        .eq("user_id", user.id)
        .select("*")
        .execute()
    )
    return _row_to_profile(response.data[0])


# Password hashing and storage
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def set_user_password(db, user: schemas.UserRead, password: str) -> schemas.UserRead:
    """Hash the provided password and update the user's record in Supabase.

    This stores a `password_hash` field on the `users` table.
    """
    if not password:
        return user
    hashed = pwd_context.hash(password)
    response = (
        supabase_client.table("users")
        .update({"password_hash": hashed})
        .eq("id", user.id)
        .select("*")
        .execute()
    )
    return _row_to_user(response.data[0])


def get_all_products(db) -> List[schemas.ProductRead]:
    response = (
        supabase_client.table("products").select("*").eq("is_active", True).execute()
    )
    return [_row_to_product(row) for row in (response.data or [])]


def get_all_products_schema(db) -> List[schemas.ProductRead]:
    return get_all_products(db)


def get_user_products(db, user: schemas.UserRead) -> List[schemas.ProductRead]:
    response = (
        supabase_client.table("products")
        .select("*")
        .eq("seller_id", user.id)
        .eq("is_active", True)
        .execute()
    )
    return [_row_to_product(row) for row in (response.data or [])]


def get_user_products_schema(db, user: schemas.UserRead) -> List[schemas.ProductRead]:
    return get_user_products(db, user)


def get_product_by_id(db, product_id: int) -> Optional[schemas.ProductRead]:
    response = (
        supabase_client.table("products")
        .select("*")
        .eq("id", product_id)
        .limit(1)
        .execute()
    )
    records = response.data or []
    return _row_to_product(records[0]) if records else None


def create_product(
    db, user: schemas.UserRead, product_data: schemas.ProductCreate
) -> schemas.ProductRead:
    payload = product_data.model_dump()
    payload["seller_id"] = user.id
    payload["sold"] = payload.get("sold") or 0
    payload["quantity"] = payload.get("quantity") or 0
    payload["is_active"] = payload.get("is_active", True)
    response = supabase_client.table("products").insert(payload).select("*").execute()
    product_row = response.data[0]
    return _row_to_product(product_row)


def update_product(
    db, product_id: int, product_data: schemas.ProductUpdate
) -> schemas.ProductRead:
    updates = {k: v for k, v in product_data.model_dump().items() if v is not None}
    response = (
        supabase_client.table("products")
        .update(updates)
        .eq("id", product_id)
        .select("*")
        .execute()
    )
    product_row = response.data[0]
    return _row_to_product(product_row)


def delete_product(db, product_id: int) -> None:
    supabase_client.table("products").delete().eq("id", product_id).execute()


def upload_product_image(
    seller_id: int, filename: str, file_bytes: bytes, content_type: Optional[str] = None
) -> str:
    """Upload a product photo to the Supabase Storage bucket and return its public URL.

    Files are stored under `<seller_id>/<uuid>.<ext>` so sellers can't collide
    with or overwrite each other's uploads.
    """
    ext = os.path.splitext(filename or "")[1].lower() or ".jpg"
    storage_path = f"{seller_id}/{uuid.uuid4().hex}{ext}"
    resolved_content_type = (
        content_type or mimetypes.guess_type(filename or "")[0] or "image/jpeg"
    )

    supabase_client.storage.from_(PRODUCT_IMAGES_BUCKET).upload(
        storage_path,
        file_bytes,
        {"content-type": resolved_content_type, "upsert": "true"},
    )
    return supabase_client.storage.from_(PRODUCT_IMAGES_BUCKET).get_public_url(
        storage_path
    )


def create_order(db, order_data: schemas.OrderCreate) -> schemas.OrderRead:
    payload = order_data.model_dump()
    payload["status"] = payload.get("status") or "Pending"
    response = supabase_client.table("orders").insert(payload).select("*").execute()
    order_row = response.data[0]
    return _row_to_order(order_row)


def record_purchase(
    db, user: schemas.UserRead, product_id: int, quantity: int
) -> schemas.OrderRead:
    """Create an order for a single product 'Buy now' action and bump its sold count."""
    product = get_product_by_id(db, product_id)
    if not product:
        raise ValueError("Product not found")

    quantity = max(1, quantity or 1)
    amount = round(float(product.price) * quantity, 2)
    order_number = f"ORD-{uuid.uuid4().hex[:8].upper()}"

    order = create_order(
        db,
        schemas.OrderCreate(
            order_number=order_number,
            item_name=product.title,
            customer_name=get_display_name(user),
            amount=amount,
            status="Pending",
            product_id=product.id,
        ),
    )

    supabase_client.table("products").update(
        {"sold": (product.sold or 0) + quantity}
    ).eq("id", product.id).execute()
    return order


def get_recent_orders(db, limit: int = 10) -> List[schemas.OrderRead]:
    response = (
        supabase_client.table("orders")
        .select("*")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return [_row_to_order(row) for row in (response.data or [])]


def get_recent_orders_schema(db, limit: int = 10) -> List[schemas.OrderRead]:
    return get_recent_orders(db, limit)


def get_dashboard_stats(db) -> schemas.DashboardStats:
    orders = supabase_client.table("orders").select("id", count="exact").execute().count
    products = (
        supabase_client.table("products").select("id", count="exact").execute().count
    )
    products_data = (
        supabase_client.table("products").select("price", "sold").execute().data or []
    )
    revenue = sum(float(item["price"]) * item["sold"] for item in products_data)
    return schemas.DashboardStats(
        orders=orders, products=products or 0, revenue=float(revenue)
    )


def _get_seller_display_name(seller_id: int) -> str:
    user = get_user(None, seller_id)
    if not user:
        return str(seller_id)
    return get_display_name(user) or user.username or f"Seller {seller_id}"


def _get_seller_summary(seller_id: int) -> dict:
    response = (
        supabase_client.table("users")
        .select("*")
        .eq("id", seller_id)
        .limit(1)
        .execute()
    )
    records = response.data or []
    if not records:
        return {"name": str(seller_id), "verified": False}

    row = records[0]
    user = _row_to_user(row)
    explicit_verified = row.get("seller_verified")
    if explicit_verified is None:
        explicit_verified = row.get("is_verified")
    if explicit_verified is None:
        explicit_verified = row.get("verified")

    return {
        "name": get_display_name(user) or user.username or f"Seller {seller_id}",
        "verified": (
            bool(explicit_verified)
            if explicit_verified is not None
            else bool(user.is_active and user.account_type == "seller")
        ),
    }


def serialize_product(product: schemas.ProductRead) -> dict:
    data = product.model_dump()
    seller = (
        _get_seller_summary(data.get("seller_id"))
        if data.get("seller_id") is not None
        else None
    )
    return {
        "id": data["id"],
        "title": data["title"],
        "category": data["category"],
        "emoji": data.get("emoji"),
        "price": data["price"],
        "unit": data.get("unit"),
        "qty": data["quantity"],
        "sold": data["sold"],
        "location": data.get("location"),
        "seller": seller["name"] if seller else "Unknown",
        "seller_verified": seller["verified"] if seller else False,
        "desc": data.get("description"),
        "img": data.get("image_url"),
        "date": data.get("date_added"),
    }


def serialize_order(order: schemas.OrderRead) -> dict:
    data = order.model_dump()
    return {
        "id": data["order_number"],
        "item": data["item_name"],
        "amount": data["amount"],
        "status": data["status"],
    }


def fetch_supabase_table(table_name: str):
    return supabase_client.table(table_name).select("*").execute()


# ---------------------------------------------------------------------------
# Payments (used by checkout.py)
# ---------------------------------------------------------------------------


def create_payment(db, payment_data: dict) -> dict:
    response = (
        supabase_client.table("payments").insert(payment_data).select("*").execute()
    )
    return response.data[0]


def update_payment(db, payment_id: int, updates: dict) -> dict:
    response = (
        supabase_client.table("payments")
        .update(updates)
        .eq("id", payment_id)
        .select("*")
        .execute()
    )
    return response.data[0]


def get_payment_by_checkout_reference(db, checkout_reference: str) -> Optional[dict]:
    response = (
        supabase_client.table("payments")
        .select("*")
        .eq("checkout_reference", checkout_reference)
        .limit(1)
        .execute()
    )
    records = response.data or []
    return records[0] if records else None


def get_orders_by_checkout_reference(
    db, checkout_reference: str
) -> List[schemas.OrderRead]:
    response = (
        supabase_client.table("orders")
        .select("*")
        .eq("checkout_reference", checkout_reference)
        .execute()
    )
    return [_row_to_order(row) for row in (response.data or [])]
