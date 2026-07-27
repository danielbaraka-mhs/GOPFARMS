import os
from dotenv import load_dotenv
from typing import List
from fastapi import FastAPI, Form, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from authlib.integrations.starlette_client import OAuth

import crud
import schemas

load_dotenv()

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_OAUTH_REDIRECT_URI = os.getenv("GOOGLE_OAUTH_REDIRECT_URI", "http://127.0.0.1:8000/oauth/callback/google")

app = FastAPI(title="GOP FARMS")
# Session middleware MUST be added first for Authlib state handling
session_secret = os.environ.get("SESSION_SECRET_KEY", "replace-with-secret")
if session_secret == "replace-with-secret":
    import warnings
    warnings.warn("SESSION_SECRET_KEY is using default value. Set it in .env for production.", RuntimeWarning)
app.add_middleware(SessionMiddleware, secret_key=session_secret)
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")

oauth = OAuth()
if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
    oauth.register(
        name="google",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )


def get_current_user(request: Request):
    session_user = request.session.get("user")
    if not session_user:
        return None
    email = session_user.get("email")
    if not email:
        return None
    return crud.get_user_by_email(None, email)


def get_dashboard_url(account_type):
    if account_type == "seller":
        return "/dashboard/seller/"
    return "/dashboard/"


def sync_session_user(request: Request, user: schemas.UserRead) -> None:
    session_user = request.session.get("user")
    if not session_user:
        return
    session_user.update(
        {
            "email": str(user.email),
            "first_name": user.first_name,
            "last_name": user.last_name,
            "name": crud.get_display_name(user),
            "account_type": user.account_type,
        }
    )
    request.session["user"] = session_user


def get_home_context(request: Request) -> dict:
    session_user = request.session.get("user")
    if session_user and not session_user.get("account_type"):
        user = get_current_user(request)
        if user:
            sync_session_user(request, user)
            session_user = request.session.get("user")

    first_name = ""
    dashboard_url = "/dashboard/"
    if session_user:
        full_name = session_user.get("name") or ""
        email = session_user.get("email") or ""
        first_name = (
            session_user.get("first_name")
            or full_name.split(" ", 1)[0]
            or email.split("@", 1)[0]
            or "there"
        )
        dashboard_url = get_dashboard_url(session_user.get("account_type"))

    return {
        "google_signin_url": "/oauth/login/google",
        "session_user": session_user,
        "nav_first_name": first_name,
        "dashboard_url": dashboard_url,
    }


@app.get("/oauth/login/google")
async def oauth_login_google(request: Request):
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        return JSONResponse({"detail": "Google OAuth is not configured."}, status_code=500)
    # Use exact redirect URI from .env that matches Google Cloud Console
    return await oauth.google.authorize_redirect(request, GOOGLE_OAUTH_REDIRECT_URI)


@app.get("/oauth/callback/google")
async def oauth_callback_google(request: Request):
    try:
        token = await oauth.google.authorize_access_token(request, leeway=300)
    except Exception as e:
        import traceback
        error_detail = str(e)
        traceback.print_exc()
        print(f"Token exchange error: {error_detail}")
        return JSONResponse({"detail": f"Token exchange failed: {error_detail}"}, status_code=400)

    try:
        user_info = token.get("userinfo")
        if not user_info:
            user_info = await oauth.google.parse_id_token(request, token, leeway=300)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"detail": f"Failed to parse user info: {str(e)}"}, status_code=400)

    if not user_info:
        return JSONResponse({"detail": "Failed to retrieve user info from Google."}, status_code=400)

    # Create the user record in Supabase if missing.
    user = None
    if user_info.get("email"):
        user = crud.create_user_if_missing(None, user_info["email"], user_info.get("given_name", ""), user_info.get("family_name", ""))

    request.session["user"] = {
        "email": user_info.get("email"),
        "first_name": user_info.get("given_name"),
        "last_name": user_info.get("family_name"),
        "name": user_info.get("name"),
        "account_type": user.account_type if user else "customer",
    }

    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(request, "farms/index.html", get_home_context(request))


@app.get("/categories/", response_class=HTMLResponse)
def categories(request: Request):
    return templates.TemplateResponse(request, "farms/categories.html")


@app.get("/dashboard/", response_class=HTMLResponse)
def dashboard(request: Request):
    user = get_current_user(request)
    if not user:
        user = crud.create_demo_user(None)
    profile = user.profile or crud.create_user_profile_if_missing(None, user)
    if user.account_type == "seller":
        return RedirectResponse(url="/dashboard/seller/", status_code=status.HTTP_303_SEE_OTHER)

    accept_lang = request.headers.get("accept-language", "")
    detected_country = ""
    if accept_lang:
        first = accept_lang.split(",")[0]
        parts = first.split("-")
        if len(parts) > 1:
            detected_country = parts[1].upper()
    return templates.TemplateResponse(
        request,
        "farms/dashboard.html",
        {
            "request": request,
            "user": user,
            "profile": profile,
            "detected_country": detected_country,
        },
    )


@app.post("/dashboard/", response_class=HTMLResponse)
def update_dashboard_profile(
    request: Request,
    full_name: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    location: str = Form(""),
    city: str = Form(""),
    country: str = Form(""),
    password: str = Form(""),
):
    user = get_current_user(request) or crud.create_demo_user(None)
    if full_name:
        parts = full_name.strip().split(None, 1)
        first_name = parts[0]
        last_name = parts[1] if len(parts) > 1 else ""
    else:
        first_name = user.first_name
        last_name = user.last_name

    user = crud.update_user(None, user, email=user.email, first_name=first_name, last_name=last_name)
    sync_session_user(request, user)
    profile_data = schemas.UserProfileBase(
        phone=phone or None,
        location=location or None,
        city=city or None,
        country=country or None,
    )
    crud.update_user_profile(None, user, profile_data)
    if password:
        crud.set_user_password(None, user, password)

    return RedirectResponse(url="/dashboard/", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/account/role", response_class=HTMLResponse)
def update_account_role(request: Request, target_type: str = Form(...)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    user = crud.update_user(None, user, account_type=target_type)
    sync_session_user(request, user)
    if target_type == "seller":
        return RedirectResponse(url="/dashboard/seller/", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/dashboard/", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/dashboard/seller/", response_class=HTMLResponse)
def dashboard_seller(request: Request):
    crud.seed_demo_data(None)
    user = get_current_user(request) or crud.create_demo_user(None)
    profile = user.profile or crud.create_user_profile_if_missing(None, user)
    if user.account_type != "seller":
        return RedirectResponse(url="/dashboard/", status_code=status.HTTP_303_SEE_OTHER)
    # detect country from Accept-Language header if profile has no country
    accept_lang = request.headers.get("accept-language", "")
    detected_country = ""
    if accept_lang:
        first = accept_lang.split(",")[0]
        parts = first.split("-")
        if len(parts) > 1:
            detected_country = parts[1].upper()
    all_products = crud.get_all_products(None)
    user_products = crud.get_user_products(None, user)
    next_id = max((product.id for product in all_products), default=0) + 1

    seller_name = crud.get_display_name(user)
    initials = "".join([part[:1].upper() for part in seller_name.split()][:2]) or "HK"
    context = {
        "request": request,
        "products": [crud.serialize_product(product) for product in all_products],
        "user_products": [crud.serialize_product(product) for product in user_products],
        "next_id": next_id,
        "seller_name": seller_name,
        "seller_initials": initials,
        "seller_location": profile.location or "Lilongwe, Central Region",
        "member_since": user.created_at.strftime("%b %Y") if user.created_at else "Jan 2024",
        "user": user,
        "profile": profile,
        "detected_country": detected_country,
    }
    return templates.TemplateResponse(request, "farms/dashboard_seller.html", context)


@app.post("/dashboard/seller/", response_class=HTMLResponse)
def update_dashboard_seller(
    request: Request,
    full_name: str = Form(""),
    shop_name: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    location: str = Form(""),
    payout_method: str = Form(""),
    city: str = Form(""),
    country: str = Form(""),
    password: str = Form(""),
):
    user = get_current_user(request) or crud.create_demo_user(None)
    if full_name:
        parts = full_name.strip().split(None, 1)
        first_name = parts[0]
        last_name = parts[1] if len(parts) > 1 else ""
    else:
        first_name = user.first_name
        last_name = user.last_name

    # Email is immutable via the profile form — always keep the current email
    user = crud.update_user(None, user, email=user.email, first_name=first_name, last_name=last_name)
    sync_session_user(request, user)

    profile_data = schemas.UserProfileBase(
        shop_name=shop_name or None,
        phone=phone or None,
        location=location or None,
        city=city or None,
        country=country or None,
        payout_method=payout_method or None,
    )
    crud.update_user_profile(None, user, profile_data)

    # If a new password was provided, hash and save it for future logins
    if password:
        crud.set_user_password(None, user, password)

    return RedirectResponse(url="/dashboard/seller/", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/logout")
def logout(request: Request):
    request.session.pop("user", None)
    return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)


@app.get("/api/products")
def api_products():
    products = crud.get_all_products(None)
    return [crud.serialize_product(product) for product in products]


@app.post("/api/products", response_model=schemas.ProductRead)
async def api_create_product(request: Request, product: schemas.ProductCreate):
    user = get_current_user(request)
    if not user or user.account_type != "seller":
        return JSONResponse({"detail": "Unauthorized"}, status_code=status.HTTP_401_UNAUTHORIZED)
    created_product = crud.create_product(None, user, product)
    return created_product


@app.patch("/api/products/{product_id}", response_model=schemas.ProductRead)
async def api_update_product(request: Request, product_id: int, product: schemas.ProductUpdate):
    user = get_current_user(request)
    if not user or user.account_type != "seller":
        return JSONResponse({"detail": "Unauthorized"}, status_code=status.HTTP_401_UNAUTHORIZED)
    existing = crud.get_product_by_id(None, product_id)
    if not existing or existing.seller_id != user.id:
        return JSONResponse({"detail": "Product not found or unauthorized"}, status_code=status.HTTP_404_NOT_FOUND)
    updated_product = crud.update_product(None, product_id, product)
    return updated_product


@app.delete("/api/products/{product_id}")
async def api_delete_product(request: Request, product_id: int):
    user = get_current_user(request)
    if not user or user.account_type != "seller":
        return JSONResponse({"detail": "Unauthorized"}, status_code=status.HTTP_401_UNAUTHORIZED)
    existing = crud.get_product_by_id(None, product_id)
    if not existing or existing.seller_id != user.id:
        return JSONResponse({"detail": "Product not found or unauthorized"}, status_code=status.HTTP_404_NOT_FOUND)
    crud.delete_product(None, product_id)
    return JSONResponse({"detail": "Deleted"}, status_code=status.HTTP_200_OK)


@app.get("/api/orders", response_model=List[schemas.OrderRead])
def api_orders():
    return crud.get_recent_orders_schema(None, limit=10)


@app.get("/api/dashboard", response_model=schemas.DashboardStats)
def api_dashboard():
    return crud.get_dashboard_stats(None)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
