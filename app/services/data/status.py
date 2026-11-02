"""Estado visible de la capa de datos: proveedores, ejecuciones y frescura.

La interfaz usa esto para responder, sin indicadores decorativos:

- qué proveedores hay y cuál está seleccionado por categoría;
- la última ejecución de cada uno y si falló;
- la fecha real del último dato de cada par de divisas;
- si los precios de un instrumento están desactualizados.

Los errores muestran el mensaje del run, no un texto inventado. Los proveedores
sin conexión real aparecen como `configured: false`; no se pintan como activos.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import FxRate, Instrument, ProviderRun, Quote
from app.services.data.sync import parse_pairs

MAX_RUNS = 30


def provider_catalog(settings: Settings) -> List[Dict[str, Any]]:
    """Catálogo declarativo. `configured` solo es True con conexión real detrás."""
    entries: List[Dict[str, Any]] = [
        {
            "name": "frankfurter",
            "category": "fx",
            "label": "Frankfurter v2 (bancos centrales, incl. BCBO/BOB)",
            "configured": True,
            "selected": settings.fx_provider == "frankfurter",
            "supports_history": True,
            "website": "https://frankfurter.dev",
            "license_url": "https://github.com/lineofflight/frankfurter/blob/main/LICENSE",
            "terms_url": "https://frankfurter.dev",
            "limits": "Sin clave ni cuota; control anti-abuso. Datos diarios (close), no tiempo real.",
        },
        {
            "name": "erapi",
            "category": "fx",
            "label": "ExchangeRate-API Open (tasa de mercado agregada)",
            "configured": True,
            "selected": settings.fx_secondary_provider == "erapi",
            "supports_history": False,
            "website": "https://www.exchangerate-api.com",
            "license_url": "https://www.exchangerate-api.com/terms",
            "terms_url": "https://www.exchangerate-api.com/terms",
            "limits": "1 petición/24 h recomendada; atribución obligatoria; no redistribuir. Caché propia.",
        },
        {
            "name": "stockanalysis",
            "category": "prices",
            "label": "StockAnalysis (históricos diarios US/DE/ES/GB)",
            "configured": True,
            "selected": settings.prices_provider == "stockanalysis",
            "supports_history": True,
            "website": "https://stockanalysis.com",
            "license_url": "https://stockanalysis.com/terms/",
            "terms_url": "https://stockanalysis.com/terms/",
            "limits": "API no oficial sin clave; cobertura verificada US/DE/ES/GB; cierres diarios (close).",
        },
        {
            "name": "sec",
            "category": "fundamentals",
            "label": "SEC EDGAR companyfacts (emisores con CIK)",
            "configured": bool(settings.sec_contact),
            "selected": bool(settings.sec_contact),
            "supports_history": True,
            "website": "https://www.sec.gov/edgar",
            "license_url": "https://www.sec.gov/about/website-policies",
            "terms_url": "https://www.sec.gov/os/accessing-edgar-data",
            "limits": "Requiere NEXO_SEC_CONTACT; ≤10 req/s; solo filas 10-K/10-Q con CIK.",
        },
        {
            "name": "ninguno",
            "category": "news",
            "label": "Noticias y calendarios",
            "configured": False,
            "selected": False,
            "supports_history": False,
            "website": "",
            "license_url": "",
            "terms_url": "",
            "limits": "Sin proveedor configurado: no se muestran noticias ni eventos. "
                      "Se necesita una fuente con licencia clara antes de activarla.",
        },
    ]
    return entries


def run_payload(run: ProviderRun) -> Dict[str, Any]:
    details = dict(run.details or {})
    return {
        "id": run.id,
        "provider": run.provider,
        "category": run.category,
        "task_key": run.task_key,
        "status": run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "attempts": run.attempts,
        "request_count": run.request_count,
        "items_fetched": run.items_fetched,
        "items_stored": run.items_stored,
        "items_skipped": run.items_skipped,
        "error": run.error,
        "details": details,
    }


def latest_runs(session: Session, limit: int = 15) -> List[Dict[str, Any]]:
    rows = (
        session.execute(select(ProviderRun).order_by(ProviderRun.started_at.desc()).limit(limit))
        .scalars().all()
    )
    return [run_payload(run) for run in rows]


def pair_status(session: Session, pairs: Sequence[Tuple[str, str]]) -> List[Dict[str, Any]]:
    """Último dato disponible por par, con todas las fuentes que lo aportaron."""
    items: List[Dict[str, Any]] = []
    today = date.today()
    for base, quote in pairs:
        rows = session.execute(
            select(FxRate).where(
                FxRate.user_id.is_(None),
                FxRate.base_currency == base,
                FxRate.quote_currency == quote,
            ).order_by(FxRate.as_of.desc()).limit(40)
        ).scalars().all()
        if not rows:
            items.append({
                "pair": f"{base}/{quote}",
                "base": base,
                "quote": quote,
                "available": False,
                "reason": "Sin datos: ejecuta una sincronización de divisas.",
            })
            continue
        latest = max(row.as_of for row in rows)
        sources = sorted({row.source for row in rows if row.as_of == latest})
        values = [
            {"source": row.source, "rate": str(row.rate), "kind": row.kind,
             "quality": row.quality}
            for row in rows if row.as_of == latest
        ]
        items.append({
            "pair": f"{base}/{quote}",
            "base": base,
            "quote": quote,
            "available": True,
            "as_of": latest.isoformat(),
            "sources": sources,
            "values": values,
            "stale": (today - latest).days > 3,
            "days_old": (today - latest).days,
            "kind": values[0]["kind"] if values else "",
        })
    return items


def price_status(session: Session, settings: Settings) -> List[Dict[str, Any]]:
    """Frescura del último cierre global por instrumento con datos de proveedor."""
    rows = session.execute(
        select(Quote).where(Quote.user_id.is_(None), Quote.adjusted.is_(False))
        .order_by(Quote.as_of.desc()).limit(500)
    ).scalars().all()
    by_instrument: Dict[int, Quote] = {}
    for row in rows:
        if row.instrument_id not in by_instrument:
            by_instrument[row.instrument_id] = row
    if not by_instrument:
        return []
    instruments = session.execute(
        select(Instrument).where(Instrument.id.in_(list(by_instrument)))
    ).scalars().all()
    today = date.today()
    items: List[Dict[str, Any]] = []
    for instrument in instruments:
        latest = by_instrument[instrument.id]
        age = (today - latest.as_of).days
        items.append({
            "instrument_uid": instrument.uid,
            "symbol": instrument.symbol,
            "name": instrument.name,
            "currency": instrument.currency,
            "market_id": instrument.market_id,
            "as_of": latest.as_of.isoformat(),
            "quality": latest.quality,
            "source": latest.source,
            "age_days": age,
            "stale": age > settings.data_stale_after_days,
            "auto_sync": instrument.auto_sync_prices,
        })
    items.sort(key=lambda item: item["symbol"])
    return items


def data_status(
    session: Session, settings: Settings, pairs: Optional[Sequence[Tuple[str, str]]] = None
) -> Dict[str, Any]:
    resolved_pairs = list(pairs if pairs is not None else parse_pairs(settings.data_sync_pairs))
    runs = latest_runs(session, MAX_RUNS)
    by_category: Dict[str, Dict[str, Any]] = {}
    for run in runs:
        current = by_category.get(run["category"])
        if current is None or (run["started_at"] or "") > (current.get("started_at") or ""):
            by_category[run["category"]] = run
    return {
        "providers": provider_catalog(settings),
        "runs": runs,
        "latest_by_category": by_category,
        "fx": pair_status(session, resolved_pairs),
        "prices": price_status(session, settings),
        "scheduler": {
            "enabled": settings.data_sync_interval_minutes > 0,
            "interval_minutes": settings.data_sync_interval_minutes,
            "pairs": [f"{b}/{q}" for b, q in resolved_pairs],
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
