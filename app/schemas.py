"""Esquemas de entrada y salida de la API (Pydantic v2).

Todos los campos llevan restricciones explícitas: la validación ocurre antes de
tocar el motor o la base de datos, y los errores se devuelven con el formato común
descrito en `docs/PLATFORM.md`.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
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


# ---------------------------------------------------------------------------
# Multimercado y cartera real
# ---------------------------------------------------------------------------

Currency = str
InstrumentType = Literal["stock", "etf", "index", "fund", "bond", "reit", "crypto", "other"]
CostMethod = Literal["fifo", "average"]
QuoteQuality = Literal["realtime", "delayed", "close", "historical", "estimated"]
MovementType = Literal[
    "deposit",
    "withdrawal",
    "buy",
    "sell",
    "dividend",
    "fee",
    "tax",
    "adjustment",
    "split",
    "transfer_in",
    "transfer_out",
]


def _currency(value: str) -> str:
    cleaned = value.strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", cleaned):
        raise ValueError("la moneda debe ser un código ISO de tres letras")
    return cleaned


class MarketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    country_code: str
    currency: str
    timezone: str
    status: str


class InstrumentCreate(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    name: str = Field(default="", max_length=255)
    market_code: str = Field(min_length=2, max_length=16)
    country_code: str = Field(default="", max_length=2)
    currency: Currency = "USD"
    instrument_type: InstrumentType = "stock"
    isin: Optional[str] = Field(default=None, max_length=12)
    cik: Optional[int] = Field(default=None, ge=0)

    @field_validator("symbol")
    @classmethod
    def _symbol(cls, value: str) -> str:
        cleaned = value.strip().upper()
        if not re.fullmatch(r"[A-Z0-9.\-]{1,32}", cleaned):
            raise ValueError("símbolo no válido")
        return cleaned

    @field_validator("market_code")
    @classmethod
    def _market(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("currency")
    @classmethod
    def _cur(cls, value: str) -> str:
        return _currency(value)

    @field_validator("isin")
    @classmethod
    def _isin(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not value.strip():
            return None
        cleaned = value.strip().upper()
        if not re.fullmatch(r"[A-Z0-9]{12}", cleaned):
            raise ValueError("el ISIN debe tener 12 caracteres alfanuméricos")
        return cleaned

    @field_validator("country_code")
    @classmethod
    def _country(cls, value: str) -> str:
        cleaned = value.strip().upper()
        if cleaned and not re.fullmatch(r"[A-Z]{2}", cleaned):
            raise ValueError("el país debe ser un código ISO de dos letras")
        return cleaned


class InstrumentOut(BaseModel):
    uid: str
    symbol: str
    name: str
    market: str
    market_name: str
    country_code: str
    currency: str
    instrument_type: str
    isin: Optional[str] = None
    cik: Optional[int] = None
    status: str


class QuoteCreate(BaseModel):
    price: Decimal = Field(gt=0, le=Decimal("1000000000"))
    as_of: date
    source: str = Field(min_length=1, max_length=64)
    quality: QuoteQuality = "close"
    currency: Optional[Currency] = None

    @field_validator("currency")
    @classmethod
    def _cur(cls, value: Optional[str]) -> Optional[str]:
        return None if value is None else _currency(value)


class QuoteOut(BaseModel):
    instrument_uid: str
    price: Decimal
    currency: str
    as_of: date
    source: str
    quality: str
    retrieved_at: datetime


class FxRateCreate(BaseModel):
    base_currency: Currency
    quote_currency: Currency
    rate: Decimal = Field(gt=0, le=Decimal("1000000000"))
    as_of: date
    source: str = Field(min_length=1, max_length=64)
    quality: QuoteQuality = "close"

    @field_validator("base_currency", "quote_currency")
    @classmethod
    def _cur(cls, value: str) -> str:
        return _currency(value)


class FxRateOut(BaseModel):
    base_currency: str
    quote_currency: str
    rate: Decimal
    as_of: date
    source: str
    quality: str
    retrieved_at: datetime


class RealAccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    broker_name: str = Field(default="", max_length=120)
    broker_country: str = Field(default="", max_length=2)
    account_type: Literal["brokerage", "retirement", "custody", "other"] = "brokerage"
    base_currency: Currency = "USD"
    cost_method: CostMethod = "fifo"
    commission_scheme: Dict[str, Any] = Field(default_factory=dict)
    allow_negative_cash: bool = False
    allow_short: bool = False

    @field_validator("base_currency")
    @classmethod
    def _cur(cls, value: str) -> str:
        return _currency(value)

    @field_validator("broker_country")
    @classmethod
    def _country(cls, value: str) -> str:
        cleaned = value.strip().upper()
        if cleaned and not re.fullmatch(r"[A-Z]{2}", cleaned):
            raise ValueError("el país debe ser un código ISO de dos letras")
        return cleaned


class RealAccountUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    broker_name: Optional[str] = Field(default=None, max_length=120)
    broker_country: Optional[str] = Field(default=None, max_length=2)
    account_type: Optional[Literal["brokerage", "retirement", "custody", "other"]] = None
    base_currency: Optional[Currency] = None
    cost_method: Optional[CostMethod] = None
    commission_scheme: Optional[Dict[str, Any]] = None
    allow_negative_cash: Optional[bool] = None
    allow_short: Optional[bool] = None
    status: Optional[Literal["active", "closed", "archived"]] = None

    @field_validator("base_currency")
    @classmethod
    def _cur(cls, value: Optional[str]) -> Optional[str]:
        return None if value is None else _currency(value)


class RealMovementCreate(BaseModel):
    movement_type: MovementType
    movement_date: date
    instrument_uid: Optional[str] = Field(default=None, max_length=36)
    # Una cantidad negativa solo tiene sentido en un split inverso; el servicio
    # valida el signo según el tipo de movimiento.
    quantity: Decimal = Field(default=Decimal("0"))
    price: Decimal = Field(default=Decimal("0"), ge=0)
    amount: Decimal = Field(default=Decimal("0"))
    fee: Decimal = Field(default=Decimal("0"), ge=0)
    tax: Decimal = Field(default=Decimal("0"), ge=0)
    currency: Optional[Currency] = None
    fx_rate: Optional[Decimal] = Field(default=None, gt=0)
    fx_date: Optional[date] = None
    fx_source: str = Field(default="", max_length=64)
    external_id: Optional[str] = Field(default=None, max_length=80)
    transfer_group: Optional[str] = Field(default=None, max_length=36)
    transfer_cost_basis: Optional[Decimal] = Field(default=None, ge=0)
    notes: str = Field(default="", max_length=4000)

    @field_validator("currency")
    @classmethod
    def _cur(cls, value: Optional[str]) -> Optional[str]:
        return None if value is None else _currency(value)

    @field_validator("instrument_uid")
    @classmethod
    def _uid(cls, value: Optional[str]) -> Optional[str]:
        return None if value is None or not value.strip() else value.strip()


class ImportConfirm(BaseModel):
    rows: Optional[List[Dict[str, Any]]] = None
    allow_partial: bool = False


class DocumentOut(BaseModel):
    id: int
    account_id: Optional[int] = None
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    status: str
    created_at: datetime


class DocumentConfirm(BaseModel):
    account_id: int
    movement: RealMovementCreate
