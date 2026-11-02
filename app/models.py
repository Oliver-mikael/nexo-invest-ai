"""Modelos persistentes del producto.

Separación de responsabilidades:

- Identidad y sesiones (`User`, `SessionToken`).
- Datos de mercado cacheados (`Company`, `CompanySnapshot`).
- Investigación (`ResearchJob`, `ResearchStep`, `Report`).
- Cartera simulada (`Portfolio`, `Position`, `Trade`).
- Control de gasto y auditoría (`UsageCounter`, `AuditEvent`, `UserSettings`).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    display_name: Mapped[str] = mapped_column(String(120), default="")
    role: Mapped[str] = mapped_column(String(20), default="user")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    settings: Mapped[Optional["UserSettings"]] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class SessionToken(Base):
    __tablename__ = "session_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    user_agent: Mapped[str] = mapped_column(String(255), default="")


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    cik: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    exchange: Mapped[str] = mapped_column(String(64), default="")
    sector: Mapped[str] = mapped_column(String(120), default="")
    industry: Mapped[str] = mapped_column(String(160), default="")
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    fiscal_year_end: Mapped[str] = mapped_column(String(8), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class CompanySnapshot(Base):
    """Caché del último análisis del motor para una empresa.

    Guarda el resultado serializado del motor financiero (métricas, escenarios,
    sensibilidad y procedencia) para que la web no repita cálculos ni descargas.
    """

    __tablename__ = "company_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    source_url: Mapped[str] = mapped_column(Text, default="")
    content_sha256: Mapped[str] = mapped_column(String(64), default="")
    data_quality: Mapped[str] = mapped_column(String(32), default="")
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ResearchJob(Base):
    __tablename__ = "research_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    company_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), nullable=True, index=True
    )
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    stage: Mapped[str] = mapped_column(String(64), default="queued")
    profile: Mapped[str] = mapped_column(String(24), default="standard")
    budget_usd: Mapped[float] = mapped_column(Float, default=0.5)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    report_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    steps: Mapped[List["ResearchStep"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="ResearchStep.id"
    )


class ResearchStep(Base):
    __tablename__ = "research_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("research_jobs.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(40))
    provider: Mapped[str] = mapped_column(String(40), default="")
    model: Mapped[str] = mapped_column(String(80), default="")
    status: Mapped[str] = mapped_column(String(24), default="pending")
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    output: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    job: Mapped[ResearchJob] = relationship(back_populates="steps")


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    company_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), nullable=True, index=True
    )
    job_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    kind: Mapped[str] = mapped_column(String(24), default="research")
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    markdown: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Portfolio(Base):
    __tablename__ = "portfolios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120), default="Cartera")
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    starting_cash: Mapped[float] = mapped_column(Float, default=100000.0)
    cash: Mapped[float] = mapped_column(Float, default=100000.0)
    benchmark: Mapped[str] = mapped_column(String(16), default="SPY")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    positions: Mapped[List["Position"]] = relationship(
        back_populates="portfolio", cascade="all, delete-orphan"
    )
    trades: Mapped[List["Trade"]] = relationship(
        back_populates="portfolio", cascade="all, delete-orphan"
    )


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (UniqueConstraint("portfolio_id", "symbol", name="uq_position_symbol"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"), index=True
    )
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    avg_cost: Mapped[float] = mapped_column(Float, default=0.0)
    thesis: Mapped[str] = mapped_column(Text, default="")
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    portfolio: Mapped[Portfolio] = relationship(back_populates="positions")


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"), index=True
    )
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    side: Mapped[str] = mapped_column(String(8))  # buy | sell
    quantity: Mapped[float] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float)
    fee: Mapped[float] = mapped_column(Float, default=0.0)
    note: Mapped[str] = mapped_column(Text, default="")
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    portfolio: Mapped[Portfolio] = relationship(back_populates="trades")


class UserSettings(Base):
    __tablename__ = "user_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    ai_profile: Mapped[str] = mapped_column(String(24), default="standard")
    monthly_budget_usd: Mapped[float] = mapped_column(Float, default=10.0)
    default_forecast_years: Mapped[int] = mapped_column(Integer, default=5)
    preferred_provider: Mapped[str] = mapped_column(String(40), default="")
    benchmark: Mapped[str] = mapped_column(String(16), default="SPY")
    preferences: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)

    user: Mapped[User] = relationship(back_populates="settings")


class UsageCounter(Base):
    __tablename__ = "usage_counters"
    __table_args__ = (UniqueConstraint("user_id", "period", name="uq_usage_period"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    period: Mapped[str] = mapped_column(String(7), index=True)  # YYYY-MM
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    jobs: Mapped[int] = mapped_column(Integer, default=0)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    subject: Mapped[str] = mapped_column(String(160), default="")
    meta: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    ip: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


# ---------------------------------------------------------------------------
# Mercados, instrumentos y datos de referencia (Fase 2)
# ---------------------------------------------------------------------------

MONEY = Numeric(28, 10)
QUANTITY = Numeric(28, 10)
PRICE = Numeric(24, 10)
RATE = Numeric(24, 10)


class Market(Base):
    """Mercado o centro de negociación identificado por su código MIC.

    El ticker no identifica un instrumento de forma global: AAPL puede existir en
    varios mercados y un mismo símbolo puede pertenecer a emisores distintos. La
    identidad estable es `Instrument.uid`.
    """

    __tablename__ = "markets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)  # MIC
    name: Mapped[str] = mapped_column(String(160))
    country_code: Mapped[str] = mapped_column(String(2), index=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Instrument(Base):
    __tablename__ = "instruments"
    __table_args__ = (
        UniqueConstraint("market_id", "symbol", name="uq_instrument_market_symbol"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Identificador interno estable e independiente del ticker; se expone en la API.
    uid: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    market_id: Mapped[int] = mapped_column(
        ForeignKey("markets.id", ondelete="RESTRICT"), index=True
    )
    country_code: Mapped[str] = mapped_column(String(2), default="")
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    instrument_type: Mapped[str] = mapped_column(String(24), default="stock")
    isin: Mapped[Optional[str]] = mapped_column(String(12), nullable=True, unique=True)
    cik: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="active")
    # Fase 5: si está activo, el planificador diario refresca precios para este
    # instrumento. Por defecto apagado: nadie genera tráfico sin consentimiento.
    auto_sync_prices: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Quote(Base):
    """Cotización con procedencia explícita; nunca se presenta como tiempo real sin serlo.

    `user_id` nulo identifica datos de un proveedor (globales). Una cotización
    introducida por un usuario es privada: no puede alterar la valoración de la
    cartera de otra persona.
    """

    __tablename__ = "quotes"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "instrument_id",
            "as_of",
            "source",
            name="uq_quote_user_instrument_day_source",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("instruments.id", ondelete="CASCADE"), index=True
    )
    price: Mapped[Any] = mapped_column(PRICE)
    currency: Mapped[str] = mapped_column(String(3))
    as_of: Mapped[Any] = mapped_column(Date, index=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    source: Mapped[str] = mapped_column(String(64))
    quality: Mapped[str] = mapped_column(String(16), default="close")
    # Semántica del precio: False = cierre sin ajustar (lo que usa la valoración),
    # True = cierre ajustado por splits/dividendos cuando la fuente lo suministra.
    adjusted: Mapped[bool] = mapped_column(Boolean, default=False)


class FxRate(Base):
    """Tipo de cambio histórico identificado por fuente y fecha.

    `rate` son unidades de `quote_currency` por una unidad de `base_currency`.
    """

    __tablename__ = "fx_rates"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "base_currency",
            "quote_currency",
            "as_of",
            "source",
            name="uq_fx_user_pair_day_source",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    base_currency: Mapped[str] = mapped_column(String(3), index=True)
    quote_currency: Mapped[str] = mapped_column(String(3), index=True)
    rate: Mapped[Any] = mapped_column(RATE)
    as_of: Mapped[Any] = mapped_column(Date, index=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    source: Mapped[str] = mapped_column(String(64))
    quality: Mapped[str] = mapped_column(String(16), default="close")
    # Natureza de la tasa cuando la fuente la identifica: official | market |
    # reference | estimated. En Bolivia no hay una única tasa representativa.
    kind: Mapped[str] = mapped_column(String(16), default="market")


# ---------------------------------------------------------------------------
# Cartera real (Fase 2 y 3). Nunca comparte tablas con la cartera simulada.
# ---------------------------------------------------------------------------


class RealAccount(Base):
    __tablename__ = "real_accounts"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_real_account_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    broker_name: Mapped[str] = mapped_column(String(120), default="")
    broker_country: Mapped[str] = mapped_column(String(2), default="")
    account_type: Mapped[str] = mapped_column(String(24), default="brokerage")
    base_currency: Mapped[str] = mapped_column(String(3), default="USD")
    cost_method: Mapped[str] = mapped_column(String(8), default="fifo")  # fifo | average
    commission_scheme: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    allow_negative_cash: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_short: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RealMovement(Base):
    """Movimiento confirmado de una cuenta real.

    Importes y cantidades usan `Numeric` y se tratan como `Decimal` en el motor.
    `fx_rate` es el tipo de cambio histórico aplicado (unidades de la moneda base
    de la cuenta por una unidad de `currency`); nunca se recalcula al valorar.
    """

    __tablename__ = "real_movements"
    __table_args__ = (
        UniqueConstraint("account_id", "dedupe_key", name="uq_real_movement_dedupe"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("real_accounts.id", ondelete="CASCADE"), index=True
    )
    instrument_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    movement_type: Mapped[str] = mapped_column(String(24), index=True)
    movement_date: Mapped[Any] = mapped_column(Date, index=True)
    settlement_date: Mapped[Optional[Any]] = mapped_column(Date, nullable=True)
    quantity: Mapped[Any] = mapped_column(QUANTITY, default=0)
    price: Mapped[Any] = mapped_column(PRICE, default=0)
    amount: Mapped[Any] = mapped_column(MONEY, default=0)
    fee: Mapped[Any] = mapped_column(MONEY, default=0)
    tax: Mapped[Any] = mapped_column(MONEY, default=0)
    currency: Mapped[str] = mapped_column(String(3))
    fx_rate: Mapped[Any] = mapped_column(RATE, default=1)
    fx_date: Mapped[Optional[Any]] = mapped_column(Date, nullable=True)
    fx_source: Mapped[str] = mapped_column(String(64), default="")
    source: Mapped[str] = mapped_column(String(16), default="manual")  # manual|import|ocr
    validation_status: Mapped[str] = mapped_column(String(16), default="confirmed")
    dedupe_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    transfer_group: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    transfer_cost_basis: Mapped[Optional[Any]] = mapped_column(MONEY, nullable=True)
    document_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    import_batch_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("import_batches.id", ondelete="SET NULL"), nullable=True
    )
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ImportBatch(Base):
    """Carga preparada y pendiente de confirmación humana."""

    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("real_accounts.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255), default="")
    content_sha256: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(16), default="preview", index=True)
    mapping: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    rows: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    valid_rows: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_rows: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class Document(Base):
    """Documento privado del usuario (extracto, captura o factura)."""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("real_accounts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    filename: Mapped[str] = mapped_column(String(255), default="")
    content_type: Mapped[str] = mapped_column(String(120), default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    storage_key: Mapped[str] = mapped_column(String(255), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="uploaded")
    extraction: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


# ---------------------------------------------------------------------------
# Fase 5: datos financieros automáticos.
# Los datos de proveedor son globales (`user_id` nulo). Lo que sigue nunca
# comparte tablas con las posiciones privadas del usuario.
# ---------------------------------------------------------------------------


class ProviderRun(Base):
    """Registro persistente de una ejecución de recopilación de datos.

    Permite auditar qué trajo cada proveedor, cuándo, cuántos registros aceptó y
    por qué falló. Un run interrumpido se detecta por `finished_at` nulo.
    """

    __tablename__ = "provider_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), index=True)
    category: Mapped[str] = mapped_column(String(24), index=True)  # fx|prices|fundamentals|news
    task_key: Mapped[str] = mapped_column(String(191), index=True)
    status: Mapped[str] = mapped_column(String(16), default="running", index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    request_count: Mapped[int] = mapped_column(Integer, default=0)
    items_fetched: Mapped[int] = mapped_column(Integer, default=0)
    items_stored: Mapped[int] = mapped_column(Integer, default=0)
    items_skipped: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    details: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)


class DataCache(Base):
    """Caché de respuestas de proveedor para no repetir solicitudes.

    La clave incluye proveedor, categoría y sujeto. Caducada, se vuelve a pedir;
    nunca se sirve una respuesta caducada como si fuera fresca.
    """

    __tablename__ = "data_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cache_key: Mapped[str] = mapped_column(String(191), unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(64), index=True)
    category: Mapped[str] = mapped_column(String(24), index=True)
    subject: Mapped[str] = mapped_column(String(191), default="")
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class FundamentalFact(Base):
    """Fundamento reportado por el emisor (SEC XBRL u otra fuente).

    `period_type` distingue anual de trimestral: nunca se mezclan. Los campos
    calculados (P/E, ROE…) se derivan en el servicio y se marcan como tales.
    """

    __tablename__ = "fundamentals"
    __table_args__ = (
        UniqueConstraint(
            "instrument_id", "period_type", "fiscal_end", "source",
            name="uq_fundamental_instrument_period_source",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("instruments.id", ondelete="CASCADE"), index=True
    )
    period_type: Mapped[str] = mapped_column(String(16))  # annual | quarter
    fiscal_start: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    fiscal_end: Mapped[date] = mapped_column(Date, index=True)
    reported_at: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    revenue: Mapped[Optional[Any]] = mapped_column(RATE, nullable=True)
    net_income: Mapped[Optional[Any]] = mapped_column(RATE, nullable=True)
    ebitda: Mapped[Optional[Any]] = mapped_column(RATE, nullable=True)
    eps_diluted: Mapped[Optional[Any]] = mapped_column(RATE, nullable=True)
    shares_outstanding: Mapped[Optional[Any]] = mapped_column(RATE, nullable=True)
    total_debt: Mapped[Optional[Any]] = mapped_column(RATE, nullable=True)
    cash: Mapped[Optional[Any]] = mapped_column(RATE, nullable=True)
    free_cash_flow: Mapped[Optional[Any]] = mapped_column(RATE, nullable=True)
    source: Mapped[str] = mapped_column(String(64), index=True)
    quality: Mapped[str] = mapped_column(String(16), default="reported")
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class NewsItem(Base):
    """Metadato de noticia o evento corporativo; nunca el artículo completo."""

    __tablename__ = "news_items"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_news_source_external"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("instruments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    category: Mapped[str] = mapped_column(String(24), default="news")  # news|earnings|dividend|split|calendar
    title: Mapped[str] = mapped_column(String(255))
    summary: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(String(512), default="")
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str] = mapped_column(String(64), index=True)
    external_id: Mapped[str] = mapped_column(String(191))
    quality: Mapped[str] = mapped_column(String(16), default="metadata")
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
