"""
Checkout router: renders the checkout page and processes payments via OneKhusa.

OneKhusa flow (Request-To-Pay / TAN model):
  1. POST /api/checkout       → validate cart, call OneKhusa to generate a TAN,
                                save a pending payment row, return the TAN to the client.
  2. Client shows the TAN    → customer pays via their bank / Airtel Money / TNM Mpamba.
  3. POST /api/webhook/onekhusa → OneKhusa fires payrequest.success (or .reversed);
                                   we verify the signature, match the referenceNumber,
                                   mark the payment completed, and update order statuses.

Wire into main.py:
    from checkout import router as checkout_router
    app.include_router(checkout_router)

Environment variables to add to .env (see bottom of this file):
    ONEKHUSA_API_KEY
    ONEKHUSA_API_SECRET
    ONEKHUSA_ORGANISATION_ID
    ONEKHUSA_MERCHANT_ACCOUNT_NUMBER
    ONEKHUSA_CAPTURED_BY          (the merchant user email registered on OneKhusa portal)
    ONEKHUSA_WEBHOOK_SECRET       (X-OneKhusa-Webhook-Signature value; copy from portal)
    ONEKHUSA_SANDBOX=true         (set to false for production)
"""

import hashlib
import hmac
import logging
import os
import threading
import time
import uuid
from decimal import Decimal
from typing import List, Optional

import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, EmailStr, Field

import crud
import schemas

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory="templates")

# ---------------------------------------------------------------------------
# OneKhusa credentials  (loaded from .env)
# ---------------------------------------------------------------------------

_SANDBOX = os.getenv("ONEKHUSA_SANDBOX", "true").lower() not in ("false", "0", "no")
_BASE_URL = (
    "https://api.onekhusa.com/sandbox/v1"
    if _SANDBOX
    else "https://api.onekhusa.com/live/v1"
)

ONEKHUSA_API_KEY = os.getenv("ONEKHUSA_API_KEY", "")
ONEKHUSA_API_SECRET = os.getenv("ONEKHUSA_API_SECRET", "")
ONEKHUSA_ORGANISATION_ID = os.getenv("ONEKHUSA_ORGANISATION_ID", "")
ONEKHUSA_MERCHANT_ACCOUNT_NUMBER = int(
    os.getenv("ONEKHUSA_MERCHANT_ACCOUNT_NUMBER", "0") or "0"
)
ONEKHUSA_CAPTURED_BY = os.getenv("ONEKHUSA_CAPTURED_BY", "")
ONEKHUSA_WEBHOOK_SECRET = os.getenv("ONEKHUSA_WEBHOOK_SECRET", "")


# ---------------------------------------------------------------------------
# OAuth 2.0 token cache  (token lasts 5 min; we refresh 30 s early)
# ---------------------------------------------------------------------------

_token_lock = threading.Lock()
_cached_token: Optional[str] = None
_token_expiry: float = 0.0  # epoch seconds


def _get_access_token() -> str:
    """Return a valid Bearer token, fetching a fresh one when needed."""
    global _cached_token, _token_expiry

    with _token_lock:
        if _cached_token and time.time() < _token_expiry - 30:
            return _cached_token

        if not all(
            [
                ONEKHUSA_API_KEY,
                ONEKHUSA_API_SECRET,
                ONEKHUSA_ORGANISATION_ID,
                ONEKHUSA_MERCHANT_ACCOUNT_NUMBER,
            ]
        ):
            raise HTTPException(
                status_code=503,
                detail=(
                    "OneKhusa credentials are not configured. "
                    "Set ONEKHUSA_API_KEY, ONEKHUSA_API_SECRET, "
                    "ONEKHUSA_ORGANISATION_ID and ONEKHUSA_MERCHANT_ACCOUNT_NUMBER in .env"
                ),
            )

        resp = httpx.post(
            f"{_BASE_URL}/account/getAccessToken",
            json={
                "apiKey": ONEKHUSA_API_KEY,
                "apiSecret": ONEKHUSA_API_SECRET,
                "organisationId": ONEKHUSA_ORGANISATION_ID,
                "merchantAccountNumber": ONEKHUSA_MERCHANT_ACCOUNT_NUMBER,
            },
            timeout=15,
        )
        if resp.status_code != 200:
            logger.error("OneKhusa token error %s: %s", resp.status_code, resp.text)
            raise HTTPException(
                status_code=502,
                detail=f"OneKhusa authentication failed: {resp.text}",
            )

        data = resp.json()
        _cached_token = data["accessToken"]
        # expiryInMinutes is always 5; convert to epoch seconds
        _token_expiry = time.time() + data.get("expiryInMinutes", 5) * 60
        return _cached_token


# ---------------------------------------------------------------------------
# OneKhusa: Request-To-Pay  (generates a TAN for the customer to pay with)
# ---------------------------------------------------------------------------


def _request_to_pay(amount: Decimal, reference_number: str, description: str) -> dict:
    """
    POST /collections/requestToPay/initiate

    Returns:
        {
            "timedAccountNumber": "11005533",   <- show this to the customer
            "expiryDate": "2026-01-05T10:01:56.412Z",
            "expiryInMinutes": 15,
            "merchantAccountNumber": 12345678
        }
    """
    token = _get_access_token()

    resp = httpx.post(
        f"{_BASE_URL}/collections/requestToPay/initiate",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept-Language": "en",
            "X-Idempotency-Key": reference_number,
        },
        json={
            "merchantAccountNumber": ONEKHUSA_MERCHANT_ACCOUNT_NUMBER,
            "transactionAmount": float(amount),
            "transactionDescription": description[:100],
            "referenceNumber": reference_number,
            "capturedBy": ONEKHUSA_CAPTURED_BY,
        },
        timeout=20,
    )

    if resp.status_code != 200:
        logger.error("OneKhusa requestToPay error %s: %s", resp.status_code, resp.text)
        raise HTTPException(
            status_code=502,
            detail=f"OneKhusa payment initiation failed: {resp.text}",
        )

    return resp.json()


# ---------------------------------------------------------------------------
# Webhook signature verification
# ---------------------------------------------------------------------------


def _verify_webhook_signature(signature: str, raw_body: bytes) -> bool:
    """
    Verify X-OneKhusa-Webhook-Signature using HMAC-SHA256 over the raw body.
    """
    if not ONEKHUSA_WEBHOOK_SECRET:
        logger.warning(
            "ONEKHUSA_WEBHOOK_SECRET not set – skipping signature check (dev only)"
        )
        return True

    expected = hmac.new(
        ONEKHUSA_WEBHOOK_SECRET.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


# ---------------------------------------------------------------------------
# Session helper
# ---------------------------------------------------------------------------


def get_session_user(request: Request) -> Optional[dict]:
    return request.session.get("user") if hasattr(request, "session") else None


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class CheckoutItemIn(BaseModel):
    product_id: int
    quantity: int = Field(gt=0)


class CustomerIn(BaseModel):
    name: str
    email: EmailStr
    phone: str
    address: str


class CheckoutRequest(BaseModel):
    customer: CustomerIn
    items: List[CheckoutItemIn]


# ---------------------------------------------------------------------------
# Page route
# ---------------------------------------------------------------------------


@router.get("/checkout", response_class=HTMLResponse, name="checkout")
async def checkout_page(request: Request):
    session_user = get_session_user(request)
    return templates.TemplateResponse(
        request,
        "farms/checkout.html",
        {
            "request": request,
            "session_user": session_user,
            "nav_first_name": (session_user or {}).get("first_name", ""),
            "dashboard_url": request.url_for("dashboard") if session_user else "#",
        },
    )


# ---------------------------------------------------------------------------
# POST /api/checkout
# Validates the cart, creates pending orders, gets a TAN from OneKhusa,
# saves a payment record, and returns the TAN to the client.
# ---------------------------------------------------------------------------


@router.post("/api/checkout")
async def submit_checkout(payload: CheckoutRequest, request: Request):
    if not payload.items:
        raise HTTPException(status_code=400, detail="Your cart is empty.")

    session_user = get_session_user(request)
    db = None

    # --- Price everything server-side; never trust the client ---
    line_items = []
    total = Decimal("0")
    descriptions = []

    for item in payload.items:
        product = crud.get_product_by_id(db, item.product_id)
        if not product:
            raise HTTPException(
                status_code=404, detail=f"Product {item.product_id} not found."
            )
        if product.quantity is not None and item.quantity > product.quantity:
            raise HTTPException(
                status_code=400,
                detail=f"Not enough stock for '{product.title}'. Only {product.quantity} left.",
            )
        line_total = Decimal(str(product.price)) * item.quantity
        total += line_total
        line_items.append(
            {"product": product, "quantity": item.quantity, "line_total": line_total}
        )
        descriptions.append(f"{item.quantity}x {product.title}")

    if total <= 0:
        raise HTTPException(
            status_code=400, detail="Order total must be greater than zero."
        )

    # Build references
    checkout_reference = f"CHK-{uuid.uuid4().hex[:12].upper()}"
    # OneKhusa referenceNumber must be 5-25 alphanumeric chars
    ok_reference = checkout_reference.replace("-", "")[:25]
    description = ", ".join(descriptions)[:100]

    # --- Create pending orders in Supabase ---
    created_orders = []
    for entry in line_items:
        product = entry["product"]
        order = crud.create_order(
            db,
            schemas.OrderCreate(
                order_number=f"ORD-{uuid.uuid4().hex[:8].upper()}",
                item_name=product.title,
                customer_name=payload.customer.name,
                amount=float(entry["line_total"]),
                status="Pending",
                product_id=product.id,
            ),
        )
        crud.supabase_client.table("orders").update(
            {"checkout_reference": checkout_reference}
        ).eq("id", order.id).execute()
        created_orders.append(order)

    # --- Call OneKhusa: generate TAN ---
    tan_data = _request_to_pay(total, ok_reference, description)

    # --- Save pending payment record ---
    payment_row = {
        "checkout_reference": checkout_reference,
        "onekhusa_reference": ok_reference,
        "timed_account_number": tan_data["timedAccountNumber"],
        "tan_expiry": tan_data["expiryDate"],
        "user_id": (session_user or {}).get("id"),
        "customer_name": payload.customer.name,
        "customer_email": payload.customer.email,
        "customer_phone": payload.customer.phone,
        "shipping_address": payload.customer.address,
        "amount": float(total),
        "currency": "MWK",
        "payment_method": "onekhusa",
        "status": "pending",
    }
    crud.create_payment(db, payment_row)

    return {
        "checkout_reference": checkout_reference,
        "timed_account_number": tan_data["timedAccountNumber"],
        "expiry_date": tan_data["expiryDate"],
        "expiry_in_minutes": tan_data["expiryInMinutes"],
        "amount": float(total),
        "currency": "MWK",
        "orders": [o.order_number for o in created_orders],
        "instructions": (
            f"Send MWK {float(total):,.2f} to account number "
            f"{tan_data['timedAccountNumber']} via your bank, "
            "Airtel Money, or TNM Mpamba. "
            f"This TAN expires in {tan_data['expiryInMinutes']} minutes."
        ),
    }


# ---------------------------------------------------------------------------
# POST /api/webhook/onekhusa
#
# ┌─────────────────────────────────────────────────────────────────────┐
# │  CALLBACK URL to register in the OneKhusa portal:                  │
# │                                                                     │
# │     https://<your-domain>/api/webhook/onekhusa                     │
# │                                                                     │
# │  Portal path:  Developers → Webhooks → Create webhook              │
# │  Subscribe to: ✅ payrequest.success   ✅ payrequest.reversed      │
# └─────────────────────────────────────────────────────────────────────┘
# ---------------------------------------------------------------------------


@router.post("/api/webhook/onekhusa", status_code=200)
async def onekhusa_webhook(
    request: Request,
    x_onekhusa_webhook_event: str = Header(default=""),
    x_onekhusa_webhook_signature: str = Header(default=""),
):
    """
    Receives payrequest.success / payrequest.reversed from OneKhusa.
    Must respond 200 quickly; OneKhusa retries hourly for 7 days.
    """
    raw_body = await request.body()

    # 1. Verify signature — never trust unverified webhooks
    if not _verify_webhook_signature(x_onekhusa_webhook_signature, raw_body):
        logger.warning("OneKhusa webhook: invalid signature – rejected")
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    # 2. Parse JSON payload
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    event = x_onekhusa_webhook_event
    meta = data.get("metaData", {})
    ok_reference = meta.get("referenceNumber", "")
    tx_status = data.get("transactionStatusCode", "")
    tx_ref = data.get("transactionReferenceNumber", "")
    tx_amount = data.get("transactionAmount", 0)

    logger.info(
        "OneKhusa webhook: event=%s ref=%s status=%s", event, ok_reference, tx_status
    )

    if not ok_reference:
        # Not one of our request-to-pay events — ignore
        return {"received": True}

    db = None

    # 3. Look up the payment by our OneKhusa reference
    try:
        resp = (
            crud.supabase_client.table("payments")
            .select("*")
            .eq("onekhusa_reference", ok_reference)
            .limit(1)
            .execute()
        )
        payment = (resp.data or [None])[0]
    except Exception as exc:
        logger.error("Webhook DB lookup error: %s", exc)
        return {
            "received": True
        }  # return 200 so OneKhusa does not keep retrying on DB blips

    if not payment:
        logger.warning(
            "Webhook: payment not found for onekhusa_reference=%s", ok_reference
        )
        return {"received": True}

    payment_id = payment["id"]
    checkout_reference = payment["checkout_reference"]

    # 4. Handle the event
    if event == "payrequest.success" and tx_status == "S":
        # Mark payment as completed
        crud.update_payment(
            db,
            payment_id,
            {
                "status": "completed",
                "gateway": "onekhusa",
                "gateway_reference": tx_ref,
                "gateway_amount": tx_amount,
            },
        )

        # Update all orders under this checkout to Paid and bump sold counts
        try:
            orders_resp = (
                crud.supabase_client.table("orders")
                .select("*")
                .eq("checkout_reference", checkout_reference)
                .execute()
            )
            for order_row in orders_resp.data or []:
                crud.supabase_client.table("orders").update({"status": "Paid"}).eq(
                    "id", order_row["id"]
                ).execute()

                if order_row.get("product_id"):
                    product = crud.get_product_by_id(db, order_row["product_id"])
                    if product:
                        crud.supabase_client.table("products").update(
                            {"sold": (product.sold or 0) + 1}
                        ).eq("id", product.id).execute()
        except Exception as exc:
            logger.error("Webhook: error updating orders after success: %s", exc)

    elif event == "payrequest.reversed":
        crud.update_payment(
            db,
            payment_id,
            {
                "status": "reversed",
                "gateway": "onekhusa",
                "gateway_reference": tx_ref,
            },
        )
        try:
            crud.supabase_client.table("orders").update({"status": "Reversed"}).eq(
                "checkout_reference", checkout_reference
            ).execute()
        except Exception as exc:
            logger.error("Webhook: error updating orders after reversal: %s", exc)

    else:
        logger.info(
            "Webhook: unhandled event=%s status=%s – no action", event, tx_status
        )

    return {"received": True}


# ---------------------------------------------------------------------------
# GET /api/checkout/status/{checkout_reference}
# Client polls this every ~10 s while waiting for the webhook to confirm payment.
# ---------------------------------------------------------------------------


@router.get("/api/checkout/status/{checkout_reference}")
async def checkout_status(checkout_reference: str):
    try:
        resp = (
            crud.supabase_client.table("payments")
            .select("status, amount, currency, timed_account_number, tan_expiry")
            .eq("checkout_reference", checkout_reference)
            .limit(1)
            .execute()
        )
        payment = (resp.data or [None])[0]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    if not payment:
        raise HTTPException(status_code=404, detail="Checkout not found")

    return {
        "checkout_reference": checkout_reference,
        "status": payment["status"],  # pending | completed | reversed
        "amount": payment["amount"],
        "currency": payment["currency"],
        "timed_account_number": payment.get("timed_account_number"),
        "tan_expiry": payment.get("tan_expiry"),
    }


# =============================================================================
# .env additions — paste these into your .env file
# =============================================================================
#
# # OneKhusa Payment Gateway
# ONEKHUSA_API_KEY=your_api_key_here
# ONEKHUSA_API_SECRET=your_api_secret_45_chars_here
# ONEKHUSA_ORGANISATION_ID=your_org_id_from_settings_profile
# ONEKHUSA_MERCHANT_ACCOUNT_NUMBER=12345678
# ONEKHUSA_CAPTURED_BY=merchant_user@yourdomain.com
# ONEKHUSA_WEBHOOK_SECRET=copy_signature_from_developers_webhooks_portal
# ONEKHUSA_SANDBOX=true       # change to false when going live
#
# =============================================================================
# Webhook Callback URL — register exactly this in the OneKhusa portal:
#
#   Developers → Webhooks → Create webhook → URL:
#
#     https://YOUR_DOMAIN.com/api/webhook/onekhusa
#
#   Subscribe to:
#     ✅  payrequest.success
#     ✅  payrequest.reversed
#
# =============================================================================
