from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr


class UserProfileBase(BaseModel):
    shop_name: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    payout_method: Optional[str] = None
    avatar_url: Optional[str] = None
    bio: Optional[str] = None


class UserProfileRead(UserProfileBase):
    id: int
    user_id: int
    created_at: datetime

    model_config = {"from_attributes": True}


class UserBase(BaseModel):
    username: Optional[str] = None
    email: Optional[EmailStr] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    account_type: Optional[str] = "customer"


class UserCreate(UserBase):
    username: str
    email: EmailStr


class UserUpdate(UserBase):
    is_active: Optional[bool] = None


class UserRead(UserBase):
    id: int
    username: str
    email: EmailStr
    is_active: bool
    created_at: datetime
    profile: Optional[UserProfileRead] = None

    model_config = {"from_attributes": True}


class ProductBase(BaseModel):
    title: str
    category: Optional[str] = None
    emoji: Optional[str] = None
    price: float
    unit: Optional[str] = None
    quantity: Optional[int] = 0
    sold: Optional[int] = 0
    description: Optional[str] = None
    location: Optional[str] = None
    image_url: Optional[str] = None
    is_active: Optional[bool] = True


class ProductCreate(ProductBase):
    pass


class ProductUpdate(ProductBase):
    title: Optional[str] = None
    price: Optional[float] = None


class ProductRead(ProductBase):
    id: int
    seller_id: int
    created_at: datetime

    model_config = {"from_attributes": True}


class OrderBase(BaseModel):
    order_number: str
    item_name: str
    customer_name: str
    amount: float
    status: Optional[str] = "Pending"
    product_id: Optional[int] = None


class OrderCreate(OrderBase):
    pass


class OrderUpdate(BaseModel):
    status: Optional[str] = None


class OrderRead(OrderBase):
    id: int
    created_at: datetime

    model_config = {"from_attributes": True}


class DashboardStats(BaseModel):
    orders: int
    products: int
    revenue: float
