"""
Checkout router: renders the checkout page and processes payments
(card, bank transfer, mobile money).

Wire this into your existing app in main.py:

    from checkout import router as checkout_router
    app.include_router(checkout_router)

Assumes:
- Jinja2 templates live in a "templates" directory next to main.py, and
  checkout.html has been placed there (adjust `templates = Jinja2Templates(...)`
  below if your project's templates directory is named differently).
- Session data is available on `request.session["user"]`, matching the
  `SESSION_SECRET_KEY` / session-based sign-in already used elsewhere in the app.
  Adjust `get_session_user()` if your app stores the logged-in user differently.
"""

import os
import uuid
from decimal import Decimal, InvalidOperation
from typing import List, Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, EmailStr, Field, field_validator

import crud
import schemas

router = APIRouter()
templates = Jinja2Templates(directory="templates")  # Adjust if your templates directory is named differently

# ---------------------------------------------------------------------------
# Payment gateway credentials
#
# Fill these in your .env file (see the .env additions provided alongside this
# file). Nothing here talks to a real gateway yet - each process_* function
# below is a clearly marked placeholder for you to wire up to whichever
# gateway you choose (Stripe, Flutterwave, Paystack, PayChangu, etc).
# ---------------------------------------------------------------------------

CARD_GATEWAY_SECRET_KEY = os.getenv("CARD_GATEWAY_SECRET_KEY", "")
CARD_GATEWAY_PUBLISHABLE_KEY = os.getenv("CARD_GATEWAY_PUBLISHABLE_KEY", "")

MOBILE_MONEY_API_KEY = os.getenv("MOBILE_MONEY_API_KEY", "")
MOBILE_MONEY_API_SECRET = os.getenv("MOBILE_MONEY_API_SECRET", "")
MOBILE_MONEY_MERCHANT_ID = os.getenv("MOBILE_MONEY_MERCHANT_ID", "")

BANK_GATEWAY_API_KEY = os.getenv("BANK_GATEWAY_API_KEY", "")
BANK_GATEWAY_API_SECRET = os.getenv("BANK_GATEWAY_API_SECRET", "")

# Static bank details shown to the customer for manual bank transfers.
BANK_TRANSFER_BANK_NAME = os.getenv("BANK_TRANSFER_BANK_NAME", "")
BANK_TRANSFER_ACCOUNT_NAME = os.getenv("BANK_TRANSFER_ACCOUNT_NAME", "")
BANK_TRANSFER_ACCOUNT_NUMBER = os.getenv("BANK_TRANSFER_ACCOUNT_NUMBER", "")
BANK_TRANSFER_BRANCH = os.getenv("BANK_TRANSFER_BRANCH", "")


def get_session_user(request: Request) -> Optional[dict]:
    return request.session.get("user") if hasattr(request, "session") else None


# ---------------------------------------------------------------------------
# Request/response models
# ---------------------------------------------------------------------------

class CheckoutItemIn(BaseModel):
    product_id: int
    quantity: int = Field(gt=0)


class CustomerIn(BaseModel):
    name: str
    email: EmailStr
    phone: str
    address: str


class CardDetailsIn(BaseModel):
    holder_name: str
    card_number: str
    expiry: str  # MM/YY
    cvv: str

    @field_validator("card_number")
    @classmethod
    def _strip_spaces(cls, v: str) -> str:
        return v.replace(" ", "")


class MobileMoneyDetailsIn(BaseModel):
    provider: str
    phone_number: str


class BankTransferDetailsIn(BaseModel):
    # No sensitive detail needed up front - we just show the customer where to send money.
    pass


class CheckoutRequest(BaseModel):
    customer: CustomerIn
    items: List[CheckoutItemIn]
    payment_method: Literal["card", "bank_transfer", "mobile_money"]
    card: Optional[CardDetailsIn] = None
    mobile_money: Optional[MobileMoneyDetailsIn] = None
    bank_transfer: Optional[BankTransferDetailsIn] = None


# ---------------------------------------------------------------------------
# Page route
# ---------------------------------------------------------------------------

@router.get("/checkout", response_class=HTMLResponse, name="checkout")
async def checkout_page(request: Request):
    session_user = get_session_user(request)
    
  
    return templates.TemplateResponse(request,
        "farms/checkout.html",
        {
            "request": request,
            "session_user": session_user,
            "nav_first_name": (session_user or {}).get("first_name", ""),
            "dashboard_url": request.url_for("dashboard") if session_user else "#",
        },
    )
   
# ---------------------------------------------------------------------------
# Payment gateway placeholders
#
# Each of these currently just simulates a successful payment so the flow is
# testable end-to-end. Replace the body with a real call to your chosen
# gateway's API using the credentials above, then return the same
# (success, gateway_reference, extra_metadata) shape.
# ---------------------------------------------------------------------------

def process_card_payment(amount: Decimal, currency: str, card: CardDetailsIn, checkout_reference: str) -> dict:
    if not CARD_GATEWAY_SECRET_KEY:
        # No gateway configured yet - fail loudly instead of pretending to charge a real card.
        raise HTTPException(status_code=503, detail="Card payments are not configured yet. Set CARD_GATEWAY_SECRET_KEY in .env.")

    # TODO: integrate your card gateway here, e.g.:
    #   response = requests.post(
    #       "https://api.<your-gateway>.com/charges",
    #       headers={"Authorization": f"Bearer {CARD_GATEWAY_SECRET_KEY}"},
    #       json={"amount": str(amount), "currency": currency, "reference": checkout_reference, ...},
    #   )
    #   data = response.json()
    #   return {"success": data["status"] == "success", "gateway_reference": data["reference"], "raw": data}
    #
    # Important: for real card processing, don't send the raw card number/CVV to your
    # own backend at all - use your gateway's client-side JS (Stripe Elements, etc.)
    # to tokenize the card in the browser and send only the resulting token here.

    return {"success": True, "gateway_reference": f"SIMULATED-CARD-{uuid.uuid4().hex[:10]}", "raw": None}


def process_mobile_money_payment(amount: Decimal, currency: str, details: MobileMoneyDetailsIn, checkout_reference: str) -> dict:
    if not MOBILE_MONEY_API_KEY:
        raise HTTPException(status_code=503, detail="Mobile money payments are not configured yet. Set MOBILE_MONEY_API_KEY in .env.")

    # TODO: integrate your mobile money gateway here, e.g.:
    #   response = requests.post(
    #       "https://api.<your-mobile-money-gateway>.com/collect",
    #       headers={"Authorization": f"Bearer {MOBILE_MONEY_API_KEY}"},
    #       json={
    #           "merchant_id": MOBILE_MONEY_MERCHANT_ID,
    #           "amount": str(amount),
    #           "currency": currency,
    #           "phone_number": details.phone_number,
    #           "provider": details.provider,
    #           "reference": checkout_reference,
    #       },
    #   )
    #   data = response.json()
    #   return {"success": data["status"] == "success", "gateway_reference": data["reference"], "raw": data}

    return {"success": True, "gateway_reference": f"SIMULATED-MOMO-{uuid.uuid4().hex[:10]}", "raw": None}


def get_bank_transfer_details() -> dict:
    return {
        "bank_name": BANK_TRANSFER_BANK_NAME,
        "account_name": BANK_TRANSFER_ACCOUNT_NAME,
        "account_number": BANK_TRANSFER_ACCOUNT_NUMBER,
        "branch": BANK_TRANSFER_BRANCH,
    }


# ---------------------------------------------------------------------------
# Checkout API
# ---------------------------------------------------------------------------

@router.get("/api/checkout/config")
async def checkout_config():
    """Non-secret values the checkout page needs (safe to expose to the browser)."""
    return {
        "card_publishable_key": CARD_GATEWAY_PUBLISHABLE_KEY,
        "bank_transfer": get_bank_transfer_details(),
    }


@router.post("/api/checkout")
async def submit_checkout(payload: CheckoutRequest, request: Request):
    if not payload.items:
        raise HTTPException(status_code=400, detail="Your cart is empty.")

    if payload.payment_method == "card" and not payload.card:
        raise HTTPException(status_code=400, detail="Card details are required for card payments.")
    if payload.payment_method == "mobile_money" and not payload.mobile_money:
        raise HTTPException(status_code=400, detail="Mobile money details are required.")

    session_user = get_session_user(request)
    db = None  # crud.py's Supabase functions accept/ignore this positional arg

    # --- Price everything server-side, never trust amounts from the client ---
    line_items = []
    total = Decimal("0")
    for item in payload.items:
        product = crud.get_product_by_id(db, item.product_id)
        if not product:
            raise HTTPException(status_code=404, detail=f"Product {item.product_id} not found.")
        if product.quantity is not None and item.quantity > product.quantity:
            raise HTTPException(status_code=400, detail=f"Not enough stock for {product.title}.")
        line_total = Decimal(str(product.price)) * item.quantity
        total += line_total
        line_items.append({"product": product, "quantity": item.quantity, "line_total": line_total})

    if total <= 0:
        raise HTTPException(status_code=400, detail="Order total must be greater than zero.")

    checkout_reference = f"CHK-{uuid.uuid4().hex[:10].upper()}"

    # --- Create one order per cart line item, reusing the existing orders flow ---
    created_orders = []
    for entry in line_items:
        product = entry["product"]
        order_number = f"ORD-{uuid.uuid4().hex[:8].upper()}"
        order = crud.create_order(
            db,
            schemas.OrderCreate(
                order_number=order_number,
                item_name=product.title,
                customer_name=payload.customer.name,
                amount=float(entry["line_total"]),
                status="Pending",
                product_id=product.id,
            ),
        )
        created_orders.append(order)
        crud.supabase_client.table("orders").update({"checkout_reference": checkout_reference}).eq("id", order.id).execute()
        crud.supabase_client.table("products").update(
            {"sold": (product.sold or 0) + entry["quantity"]}
        ).eq("id", product.id).execute()

    # --- Create the payment record (pending) ---
    payment_row = {
        "checkout_reference": checkout_reference,
        "user_id": session_user.get("id") if session_user else None,
        "customer_name": payload.customer.name,
        "customer_email": payload.customer.email,
        "customer_phone": payload.customer.phone,
        "shipping_address": payload.customer.address,
        "amount": float(total),
        "currency": "USD",
        "payment_method": payload.payment_method,
        "status": "pending",
    }

    if payload.payment_method == "card":
        card = payload.card
        payment_row["card_last4"] = card.card_number[-4:]
        payment_row["card_brand"] = _guess_card_brand(card.card_number)
    elif payload.payment_method == "mobile_money":
        payment_row["mobile_provider"] = payload.mobile_money.provider
        payment_row["mobile_number"] = payload.mobile_money.phone_number
    elif payload.payment_method == "bank_transfer":
        bank_details = get_bank_transfer_details()
        payment_row["bank_name"] = bank_details["bank_name"]
        payment_row["bank_account_reference"] = checkout_reference

    payment = crud.create_payment(db, payment_row)

    # --- Run the payment through the relevant gateway ---
    if payload.payment_method == "card":
        result = process_card_payment(total, "USD", payload.card, checkout_reference)
        new_status = "completed" if result["success"] else "failed"
        crud.update_payment(db, payment["id"], {
            "status": new_status,
            "gateway": "card_gateway",
            "gateway_reference": result.get("gateway_reference"),
        })
    elif payload.payment_method == "mobile_money":
        result = process_mobile_money_payment(total, "USD", payload.mobile_money, checkout_reference)
        new_status = "completed" if result["success"] else "failed"
        crud.update_payment(db, payment["id"], {
            "status": new_status,
            "gateway": "mobile_money_gateway",
            "gateway_reference": result.get("gateway_reference"),
        })
    else:
        # Bank transfer: money moves outside our system, so it stays "pending"
        # until you confirm it (manually, or via a webhook from your bank gateway)
        # and flip the row to "completed" in Supabase.
        new_status = "pending"

    return {
        "checkout_reference": checkout_reference,
        "status": new_status,
        "total": float(total),
        "orders": [order.order_number for order in created_orders],
        "bank_transfer": get_bank_transfer_details() if payload.payment_method == "bank_transfer" else None,
    }


def _guess_card_brand(card_number: str) -> str:
    if card_number.startswith("4"):
        return "Visa"
    if card_number[:2] in {"51", "52", "53", "54", "55"}:
        return "Mastercard"
    if card_number[:2] in {"34", "37"}:
        return "American Express"
    return "Card"
