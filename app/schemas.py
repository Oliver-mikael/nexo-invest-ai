"""Esquemas de entrada y salida de la API (Pydantic v2).

Todos los campos llevan restricciones explícitas: la validación ocurre antes de
tocar el motor o la base de datos, y los errores se devuelven con el formato común
descrito en `docs/PLATFORM.md`.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")

Profile = Literal["basic", "standard", "deep"]


class RegisterRequest(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=10, max_length=200)
    display_name: str = Field(default="", max_length=120)

    @field_validator("email")
    @classmethod
    def _valid_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not EMAIL_RE.match(normalized):
            raise ValueError("email no válido")
        return normalized


class LoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=1, max_length=200)

    @field_validator("email")
    @classmethod
    def _normalize(cls, value: str) -> str:
        return value.strip().lower()


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    display_name: str
    role: str
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: UserOut


class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ticker: str
    cik: Optional[int] = None
    name: str
    exchange: str = ""
    sector: str = ""
    industry: str = ""
    currency: str = "USD"


class CompanySearchResponse(BaseModel):
    items: List[CompanyOut]
    total: int
    query: str


class ValuationRequest(BaseModel):
    forecast_years: int = Field(default=5, ge=1, le=15)
    discount_rate: float = Field(default=0.085, gt=0, le=0.40)
    terminal_growth: float = Field(default=0.025, ge=-0.05, lt=0.40)
    growth_rate: float = Field(default=0.04, ge=-0.5, le=0.5)
    fcf_adjustment: float = Field(default=0.0, ge=-0.9, le=1.0)
    share_price: Optional[float] = Field(default=None, gt=0, le=1_000_000)
    sensitivity_steps: int = Field(default=2, ge=1, le=4)

    @field_validator("terminal_growth")
    @classmethod
    def _below_discount(cls, value: float, info: Any) -> float:
        discount = (info.data or {}).get("discount_rate")
        if discount is not None and value >= discount:
            raise ValueError("terminal_growth debe ser menor que discount_rate")
        return value


class ResearchCreateRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=12)
    profile: Profile = "standard"
    budget_usd: Optional[float] = Field(default=None, gt=0, le=5)
    forecast_years: int = Field(default=5, ge=1, le=15)

    @field_validator("ticker")
    @classmethod
    def _ticker(cls, value: str) -> str:
        cleaned = value.strip().upper()
        if not re.fullmatch(r"[A-Z0-9.\-]{1,12}", cleaned):
            raise ValueError("ticker no válido")
        return cleaned


class PortfolioCreate(BaseModel):
    name: str = Field(default="Cartera", max_length=120)
    starting_cash: float = Field(default=100_000.0, gt=0, le=1_000_000_000)
    currency: str = Field(default="USD", max_length=8)
    benchmark: str = Field(default="SPY", max_length=16)


class TradeCreate(BaseModel):
    symbol: str = Field(min_length=1, max_length=12)
    side: Literal["buy", "sell"]
    quantity: float = Field(gt=0, le=1_000_000)
    price: float = Field(gt=0, le=1_000_000)
    fee: float = Field(default=0.0, ge=0, le=10_000)
    note: str = Field(default="", max_length=2000)
    thesis: str = Field(default="", max_length=4000)

    @field_validator("symbol")
    @classmethod
    def _symbol(cls, value: str) -> str:
        return value.strip().upper()


class SettingsUpdate(BaseModel):
    ai_profile: Optional[Profile] = None
    monthly_budget_usd: Optional[float] = Field(default=None, ge=0, le=10_000)
    default_forecast_years: Optional[int] = Field(default=None, ge=1, le=15)
    preferred_provider: Optional[str] = Field(default=None, max_length=40)
    benchmark: Optional[str] = Field(default=None, max_length=16)


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    database: str
    ai_enabled: bool
    engine: str
    time: datetime
