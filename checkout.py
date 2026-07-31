"""
Checkout router — OneKhusa Request-To-Pay integration.

Flow:
  1. POST /api/checkout
       • Validate cart server-side
       • Create pending payment row  (payments table)
       • Call OneKhusa → get TAN
       • Create onekhusa_transactions row  (status=pending, TAN stored)
       • Return TAN + instructions to client
       • Client polls GET /api/checkout/status/{ref} every 10 s

  2. Customer pays using the TAN via bank / Airtel Money / TNM Mpamba

  3. POST /api/webhook/onekhusa  (called by OneKhusa, NOT the client)
       • Verify HMAC-SHA256 signature
       • Log raw event → payment_notifications
       • Detect duplicate delivery
       • On payrequest.success:
           - Update onekhusa_transactions (confirmed amounts, payer info)
           - Update payments.status = 'completed'
           - Update orders.status   = 'Paid'
           - Bump products.sold
           - Send confirmation email/SMS to customer  ← ONLY here, never earlier
       • On payrequest.reversed:
           - Mark everything Reversed

Wire into main.py:
    from checkout import router as checkout_router
    app.include_router(checkout_router)
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

# ─────────────────────────────────────────────────────────────────────────────
# OneKhusa config
# ─────────────────────────────────────────────────────────────────────────────
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

# ─────────────────────────────────────────────────────────────────────────────
# Token cache (OAuth 2.0, expires every 5 min)
# ─────────────────────────────────────────────────────────────────────────────
_token_lock = threading.Lock()
_cached_token: Optional[str] = None
_token_expiry: float = 0.0


def _get_access_token() -> str:
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
                    "OneKhusa credentials missing. Set ONEKHUSA_API_KEY, "
                    "ONEKHUSA_API_SECRET, ONEKHUSA_ORGANISATION_ID and "
                    "ONEKHUSA_MERCHANT_ACCOUNT_NUMBER in .env"
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
            raise HTTPException(502, f"OneKhusa auth failed: {resp.text}")
        data = resp.json()
        _cached_token = data["accessToken"]
        _token_expiry = time.time() + data.get("expiryInMinutes", 5) * 60
        return _cached_token


# ─────────────────────────────────────────────────────────────────────────────
# OneKhusa: Request-To-Pay → returns TAN
# ─────────────────────────────────────────────────────────────────────────────
def _request_to_pay(amount: Decimal, reference_number: str, description: str) -> dict:
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
        logger.error("OneKhusa requestToPay %s: %s", resp.status_code, resp.text)
        raise HTTPException(502, f"OneKhusa initiation failed: {resp.text}")
    return resp.json()


# ─────────────────────────────────────────────────────────────────────────────
# Webhook signature verification
# ─────────────────────────────────────────────────────────────────────────────
def _verify_signature(signature: str, raw_body: bytes) -> bool:
    if not ONEKHUSA_WEBHOOK_SECRET:
        logger.warning(
            "ONEKHUSA_WEBHOOK_SECRET not set — skipping signature check (dev only)"
        )
        return True
    expected = hmac.new(
        ONEKHUSA_WEBHOOK_SECRET.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


# ─────────────────────────────────────────────────────────────────────────────
# Customer confirmation (email / SMS)
# Called ONLY from the webhook after OneKhusa confirms payment.
# ─────────────────────────────────────────────────────────────────────────────
def _send_payment_confirmation(
    notification_id: int,
    customer_email: str,
    customer_name: str,
    customer_phone: str,
    checkout_reference: str,
    amount: float,
    currency: str,
    source_institution: str,
    transaction_reference: str,
) -> None:
    """
    Send a confirmation email and/or SMS to the customer.

    The notification_id row in payment_notifications is updated with
    the result so you have a full audit trail.

    ── Email ────────────────────────────────────────────────────────────────
    Drop in any SMTP / transactional email provider:
      • smtplib (stdlib)                 — free, needs SMTP credentials
      • sendgrid-python                  — pip install sendgrid
      • mailersend                       — pip install mailersend
      • boto3 SES                        — if you're on AWS
    ── SMS ──────────────────────────────────────────────────────────────────
      • Twilio                           — pip install twilio
      • Africa's Talking                 — pip install africastalking
      • BulkSMS Malawi                   — HTTP API, use httpx
    """
    db = None
    sent_channels = []
    error_message = None

    subject = f"Payment confirmed — {checkout_reference}"
    body = (
        f"Dear {customer_name},\n\n"
        f"✅  Your payment of {currency} {amount:,.2f} has been received and confirmed.\n\n"
        f"  Reference:     {checkout_reference}\n"
        f"  Transaction:   {transaction_reference}\n"
        f"  Paid via:      {source_institution}\n\n"
        f"Your order is now being processed. "
        f"Thank you for shopping with GOP FARMS!\n\n"
        f"— GOP FARMS Team"
    )

    # ── EMAIL ────────────────────────────────────────────────────────────────
    SMTP_HOST = os.getenv("SMTP_HOST", "")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
    SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER)

    if SMTP_HOST and SMTP_USER and customer_email:
        try:
            import smtplib
            from email.mime.text import MIMEText

            msg = MIMEText(body)
            msg["Subject"] = subject
            msg["From"] = SMTP_FROM
            msg["To"] = customer_email
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.sendmail(SMTP_FROM, [customer_email], msg.as_string())
            sent_channels.append("email")
            logger.info(
                "Confirmation email sent to %s for %s",
                customer_email,
                checkout_reference,
            )
        except Exception as exc:
            error_message = f"email: {exc}"
            logger.error("Failed to send confirmation email: %s", exc)

    # ── SMS (Africa's Talking example) ───────────────────────────────────────
    AT_API_KEY = os.getenv("AT_API_KEY", "")
    AT_USERNAME = os.getenv("AT_USERNAME", "")
    AT_SENDER = os.getenv("AT_SENDER_ID", "GOPFARMS")

    if AT_API_KEY and AT_USERNAME and customer_phone:
        try:
            import africastalking  # pip install africastalking

            africastalking.initialize(AT_USERNAME, AT_API_KEY)
            sms = africastalking.SMS
            sms_body = (
                f"GOP FARMS: Payment of {currency} {amount:,.2f} confirmed. "
                f"Ref: {checkout_reference}. Thank you!"
            )
            sms.send(sms_body, [customer_phone], AT_SENDER)
            sent_channels.append("sms")
            logger.info(
                "Confirmation SMS sent to %s for %s", customer_phone, checkout_reference
            )
        except Exception as exc:
            msg = f"sms: {exc}"
            error_message = f"{error_message}; {msg}" if error_message else msg
            logger.error("Failed to send confirmation SMS: %s", exc)

    # ── Update notification row with result ───────────────────────────────────
    try:
        update_payload = {
            "notification_sent": bool(sent_channels),
            "notification_channel": (
                " + ".join(sent_channels) if sent_channels else None
            ),
        }
        if sent_channels:
            update_payload["notification_sent_at"] = "NOW()"
        if error_message:
            update_payload["notification_error"] = error_message
        crud.supabase_client.table("payment_notifications").update(update_payload).eq(
            "id", notification_id
        ).execute()
    except Exception as exc:
        logger.error("Failed to update notification row %s: %s", notification_id, exc)


# ─────────────────────────────────────────────────────────────────────────────
# Session helper
# ─────────────────────────────────────────────────────────────────────────────
def get_session_user(request: Request) -> Optional[dict]:
    return request.session.get("user") if hasattr(request, "session") else None


# ─────────────────────────────────────────────────────────────────────────────
# Request models
# ─────────────────────────────────────────────────────────────────────────────
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


# ─────────────────────────────────────────────────────────────────────────────
# Page route
# ─────────────────────────────────────────────────────────────────────────────
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


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/checkout
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/api/checkout")
async def submit_checkout(payload: CheckoutRequest, request: Request):
    """
    1. Validate cart + compute total server-side
    2. Create pending orders
    3. Insert pending row into `payments`
    4. Call OneKhusa requestToPay/initiate → get TAN
    5. Insert row into `onekhusa_transactions` with TAN + expiry
    6. Return TAN + instructions to client
    """
    if not payload.items:
        raise HTTPException(400, "Your cart is empty.")

    session_user = get_session_user(request)
    db = None

    # ── 1. Validate cart ──────────────────────────────────────────────────────
    line_items = []
    total = Decimal("0")
    descriptions = []

    for item in payload.items:
        product = crud.get_product_by_id(db, item.product_id)
        if not product:
            raise HTTPException(404, f"Product {item.product_id} not found.")
        if product.quantity is not None and item.quantity > product.quantity:
            raise HTTPException(
                400,
                f"Not enough stock for '{product.title}'. Only {product.quantity} left.",
            )
        line_total = Decimal(str(product.price)) * item.quantity
        total += line_total
        line_items.append(
            {"product": product, "quantity": item.quantity, "line_total": line_total}
        )
        descriptions.append(f"{item.quantity}x {product.title}")

    if total <= 0:
        raise HTTPException(400, "Order total must be greater than zero.")

    # ── Build references ──────────────────────────────────────────────────────
    checkout_reference = f"CHK-{uuid.uuid4().hex[:12].upper()}"
    # OneKhusa referenceNumber must be 5-25 alphanumeric chars
    ok_reference = checkout_reference.replace("-", "")[:25]
    description = ", ".join(descriptions)[:100]

    # ── 2. Create pending orders ──────────────────────────────────────────────
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

    # ── 3. Insert pending payment row ─────────────────────────────────────────
    payment_row = {
        "checkout_reference": checkout_reference,
        "onekhusa_reference": ok_reference,
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

    # ── 4. Call OneKhusa → TAN ────────────────────────────────────────────────
    tan_data = _request_to_pay(total, ok_reference, description)

    # ── 5. Insert onekhusa_transactions row ───────────────────────────────────
    crud.supabase_client.table("onekhusa_transactions").insert(
        {
            "checkout_reference": checkout_reference,
            "onekhusa_reference": ok_reference,
            "timed_account_number": tan_data["timedAccountNumber"],
            "tan_expiry": tan_data["expiryDate"],
            "merchant_account_number": tan_data.get("merchantAccountNumber"),
            "status": "pending",
        }
    ).execute()

    # ── 6. Return TAN to client ───────────────────────────────────────────────
    return {
        "checkout_reference": checkout_reference,
        "timed_account_number": tan_data["timedAccountNumber"],
        "expiry_date": tan_data["expiryDate"],
        "expiry_in_minutes": tan_data["expiryInMinutes"],
        "amount": float(total),
        "currency": "MWK",
        "orders": [o.order_number for o in created_orders],
        "status": "pending",
        "instructions": (
            f"Send MWK {float(total):,.2f} to account number "
            f"<strong>{tan_data['timedAccountNumber']}</strong> "
            "via your bank, Airtel Money, or TNM Mpamba. "
            f"This TAN expires in {tan_data['expiryInMinutes']} minutes. "
            "You will receive a confirmation SMS/email once we receive your payment."
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/webhook/onekhusa
#
# ┌──────────────────────────────────────────────────────────────────────────┐
# │  CALLBACK URL to register in the OneKhusa portal:                       │
# │                                                                          │
# │     https://<your-domain>/api/webhook/onekhusa                          │
# │                                                                          │
# │  Developers → Webhooks → Create webhook                                 │
# │  Subscribe to:  ✅ payrequest.success   ✅ payrequest.reversed          │
# └──────────────────────────────────────────────────────────────────────────┘
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/api/webhook/onekhusa", status_code=200)
async def onekhusa_webhook(
    request: Request,
    x_onekhusa_webhook_event: str = Header(default=""),
    x_onekhusa_webhook_signature: str = Header(default=""),
):
    """
    Receives payrequest.success / payrequest.reversed from OneKhusa.
    Customer confirmation is sent HERE — never before this point.
    Responds 200 immediately; OneKhusa retries hourly for 7 days.
    """
    raw_body = await request.body()

    # ── Verify signature ──────────────────────────────────────────────────────
    if not _verify_signature(x_onekhusa_webhook_signature, raw_body):
        logger.warning("OneKhusa webhook: bad signature — rejected")
        raise HTTPException(401, "Invalid webhook signature")

    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    event = x_onekhusa_webhook_event
    meta = data.get("metaData", {})
    ok_reference = meta.get("referenceNumber", "")
    tx_status = data.get("transactionStatusCode", "")
    tx_ref = data.get("transactionReferenceNumber", "")
    tx_amount = data.get("transactionAmount")
    tx_fee = data.get("transactionFee")
    tx_date = data.get("transactionDate")
    connector_id = data.get("connectorId")
    resp_code = data.get("responseCode")
    src_acct_num = data.get("sourceAccountNumber") or meta.get("sourceAccountNumber")
    src_acct_name = data.get("sourceAccountName") or meta.get("sourceAccountName")
    src_inst = data.get("sourceInstitution") or meta.get("sourceInstitution")
    tan = meta.get("timedAccountNumber")

    logger.info(
        "OneKhusa webhook: event=%s ref=%s status=%s tx=%s",
        event,
        ok_reference,
        tx_status,
        tx_ref,
    )

    if not ok_reference:
        return {"received": True}  # not one of ours — ignore silently

    db = None

    # ── Look up the onekhusa_transactions row ─────────────────────────────────
    try:
        ok_resp = (
            crud.supabase_client.table("onekhusa_transactions")
            .select(
                "*, payments(id, checkout_reference, user_id, customer_name, "
                "customer_email, customer_phone, amount, currency)"
            )
            .eq("onekhusa_reference", ok_reference)
            .limit(1)
            .execute()
        )
        ok_tx = (ok_resp.data or [None])[0]
    except Exception as exc:
        logger.error("Webhook DB lookup error: %s", exc)
        return {"received": True}  # 200 so OneKhusa stops retrying on DB blip

    if not ok_tx:
        logger.warning("Webhook: no onekhusa_transaction for ref=%s", ok_reference)
        return {"received": True}

    ok_tx_id = ok_tx["id"]
    checkout_reference = ok_tx["checkout_reference"]
    payment = ok_tx.get("payments") or {}
    customer_email = payment.get("customer_email", "")
    customer_name = payment.get("customer_name", "")
    customer_phone = payment.get("customer_phone", "")
    confirmed_amount = float(tx_amount) if tx_amount else payment.get("amount", 0)
    currency = payment.get("currency", "MWK")

    # ── Duplicate detection ───────────────────────────────────────────────────
    dup_check = (
        crud.supabase_client.table("payment_notifications")
        .select("id")
        .eq("transaction_reference", tx_ref)
        .eq("event_code", event)
        .limit(1)
        .execute()
    )
    is_duplicate = bool(dup_check.data)

    # ── Log every webhook event to payment_notifications ─────────────────────
    notif_row = {
        "checkout_reference": checkout_reference,
        "onekhusa_reference": ok_reference,
        "onekhusa_transaction_id": ok_tx_id,
        "event_code": event,
        "transaction_reference": tx_ref,
        "transaction_status_code": tx_status,
        "transaction_amount": tx_amount,
        "transaction_fee": tx_fee,
        "transaction_date": tx_date,
        "source_account_number": src_acct_num,
        "source_account_name": src_acct_name,
        "source_institution": src_inst,
        "connector_id": connector_id,
        "response_code": resp_code,
        "raw_payload": data,
        "is_duplicate": is_duplicate,
    }
    notif_resp = (
        crud.supabase_client.table("payment_notifications")
        .insert(notif_row)
        .select("id")
        .execute()
    )
    notification_id = (notif_resp.data or [{}])[0].get("id")

    if is_duplicate:
        logger.info(
            "Webhook duplicate detected for tx_ref=%s — logged, no further action",
            tx_ref,
        )
        return {"received": True}

    # ── Handle payrequest.success ─────────────────────────────────────────────
    if event == "payrequest.success" and tx_status == "S":

        # Update onekhusa_transactions
        crud.supabase_client.table("onekhusa_transactions").update(
            {
                "status": "completed",
                "transaction_reference": tx_ref,
                "transaction_status_code": tx_status,
                "transaction_amount": tx_amount,
                "transaction_fee": tx_fee,
                "transaction_date": tx_date,
                "connector_id": connector_id,
                "response_code": resp_code,
                "source_account_number": src_acct_num,
                "source_account_name": src_acct_name,
                "source_institution": src_inst,
                "confirmed_at": "NOW()",
            }
        ).eq("id", ok_tx_id).execute()

        # Update payments status
        crud.supabase_client.table("payments").update(
            {
                "status": "completed",
            }
        ).eq("checkout_reference", checkout_reference).execute()

        # Update all orders under this checkout to Paid + bump sold counts
        try:
            orders_resp = (
                crud.supabase_client.table("orders")
                .select("id, product_id, amount")
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
            logger.error("Webhook: error updating orders: %s", exc)

        # ── Send customer confirmation — ONLY triggered from here ─────────────
        if notification_id and customer_email:
            try:
                _send_payment_confirmation(
                    notification_id=notification_id,
                    customer_email=customer_email,
                    customer_name=customer_name,
                    customer_phone=customer_phone,
                    checkout_reference=checkout_reference,
                    amount=confirmed_amount,
                    currency=currency,
                    source_institution=src_inst or "OneKhusa",
                    transaction_reference=tx_ref or "",
                )
            except Exception as exc:
                logger.error("Confirmation send failed: %s", exc)

    # ── Handle payrequest.reversed ────────────────────────────────────────────
    elif event == "payrequest.reversed":
        crud.supabase_client.table("onekhusa_transactions").update(
            {
                "status": "reversed",
                "transaction_reference": tx_ref,
                "transaction_status_code": tx_status,
                "transaction_date": tx_date,
            }
        ).eq("id", ok_tx_id).execute()

        crud.supabase_client.table("payments").update({"status": "reversed"}).eq(
            "checkout_reference", checkout_reference
        ).execute()

        try:
            crud.supabase_client.table("orders").update({"status": "Reversed"}).eq(
                "checkout_reference", checkout_reference
            ).execute()
        except Exception as exc:
            logger.error("Webhook reversal order update error: %s", exc)

    else:
        logger.info("Webhook: unhandled event=%s / status=%s", event, tx_status)

    return {"received": True}


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/checkout/status/{checkout_reference}
# Client polls this every ~10 s while waiting for OneKhusa to confirm.
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/api/checkout/status/{checkout_reference}")
async def checkout_status(checkout_reference: str):
    try:
        resp = (
            crud.supabase_client.table("onekhusa_transactions")
            .select(
                "status, timed_account_number, tan_expiry, transaction_reference, "
                "transaction_amount, source_institution, confirmed_at, "
                "payments(amount, currency, customer_name, customer_email)"
            )
            .eq("checkout_reference", checkout_reference)
            .limit(1)
            .execute()
        )
        tx = (resp.data or [None])[0]
    except Exception as exc:
        raise HTTPException(500, str(exc))

    if not tx:
        raise HTTPException(404, "Checkout not found")

    payment = tx.get("payments") or {}
    return {
        "checkout_reference": checkout_reference,
        "status": tx["status"],  # pending|completed|reversed|expired|failed
        "timed_account_number": tx.get("timed_account_number"),
        "tan_expiry": tx.get("tan_expiry"),
        "amount": payment.get("amount"),
        "currency": payment.get("currency", "MWK"),
        "customer_name": payment.get("customer_name"),
        "transaction_reference": tx.get("transaction_reference"),
        "confirmed_amount": tx.get("transaction_amount"),
        "source_institution": tx.get("source_institution"),
        "confirmed_at": tx.get("confirmed_at"),
        # user-friendly message the frontend can display directly
        "message": (
            "✅ Payment confirmed! Your order is being processed."
            if tx["status"] == "completed"
            else (
                "⚠️ Payment was reversed. Please contact support."
                if tx["status"] == "reversed"
                else "⏳ Awaiting payment. Please complete the transfer to the TAN."
            )
        ),
    }
