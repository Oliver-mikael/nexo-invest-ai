"""Datos de referencia: mercados con código MIC.

No son cotizaciones ni datos de mercado en vivo. Solo permiten identificar el
centro de negociación de un instrumento sin usar el ticker como identificador
global. La lista se puede ampliar con una migración o desde la API.
"""

from __future__ import annotations

from typing import Dict, List

from sqlalchemy import select

from app.db import session_scope
from app.models import Market

MARKETS: List[Dict[str, str]] = [
    {"code": "XNYS", "name": "New York Stock Exchange", "country_code": "US", "currency": "USD", "timezone": "America/New_York"},
    {"code": "XNAS", "name": "Nasdaq Stock Market", "country_code": "US", "currency": "USD", "timezone": "America/New_York"},
    {"code": "ARCX", "name": "NYSE Arca", "country_code": "US", "currency": "USD", "timezone": "America/New_York"},
    {"code": "XTSE", "name": "Toronto Stock Exchange", "country_code": "CA", "currency": "CAD", "timezone": "America/Toronto"},
    {"code": "XMEX", "name": "Bolsa Mexicana de Valores", "country_code": "MX", "currency": "MXN", "timezone": "America/Mexico_City"},
    {"code": "BVMF", "name": "B3 Brasil Bolsa Balcão", "country_code": "BR", "currency": "BRL", "timezone": "America/Sao_Paulo"},
    {"code": "XBUE", "name": "Bolsas y Mercados Argentinos", "country_code": "AR", "currency": "ARS", "timezone": "America/Argentina/Buenos_Aires"},
    {"code": "XSGO", "name": "Bolsa de Comercio de Santiago", "country_code": "CL", "currency": "CLP", "timezone": "America/Santiago"},
    {"code": "XBOG", "name": "Bolsa de Valores de Colombia", "country_code": "CO", "currency": "COP", "timezone": "America/Bogota"},
    {"code": "XLIM", "name": "Bolsa de Valores de Lima", "country_code": "PE", "currency": "PEN", "timezone": "America/Lima"},
    {"code": "XBOL", "name": "Bolsa Boliviana de Valores", "country_code": "BO", "currency": "BOB", "timezone": "America/La_Paz"},
    {"code": "XLON", "name": "London Stock Exchange", "country_code": "GB", "currency": "GBP", "timezone": "Europe/London"},
    {"code": "XPAR", "name": "Euronext Paris", "country_code": "FR", "currency": "EUR", "timezone": "Europe/Paris"},
    {"code": "XAMS", "name": "Euronext Amsterdam", "country_code": "NL", "currency": "EUR", "timezone": "Europe/Amsterdam"},
    {"code": "XETR", "name": "Xetra", "country_code": "DE", "currency": "EUR", "timezone": "Europe/Berlin"},
    {"code": "XFRA", "name": "Frankfurt Stock Exchange", "country_code": "DE", "currency": "EUR", "timezone": "Europe/Berlin"},
    {"code": "XMAD", "name": "Bolsa de Madrid", "country_code": "ES", "currency": "EUR", "timezone": "Europe/Madrid"},
    {"code": "XMIL", "name": "Borsa Italiana", "country_code": "IT", "currency": "EUR", "timezone": "Europe/Rome"},
    {"code": "XSWX", "name": "SIX Swiss Exchange", "country_code": "CH", "currency": "CHF", "timezone": "Europe/Zurich"},
    {"code": "XTKS", "name": "Tokyo Stock Exchange", "country_code": "JP", "currency": "JPY", "timezone": "Asia/Tokyo"},
    {"code": "XHKG", "name": "Hong Kong Stock Exchange", "country_code": "HK", "currency": "HKD", "timezone": "Asia/Hong_Kong"},
    {"code": "XSHG", "name": "Shanghai Stock Exchange", "country_code": "CN", "currency": "CNY", "timezone": "Asia/Shanghai"},
    {"code": "XNSE", "name": "National Stock Exchange of India", "country_code": "IN", "currency": "INR", "timezone": "Asia/Kolkata"},
    {"code": "XBOM", "name": "Bombay Stock Exchange", "country_code": "IN", "currency": "INR", "timezone": "Asia/Kolkata"},
    {"code": "XKRX", "name": "Korea Exchange", "country_code": "KR", "currency": "KRW", "timezone": "Asia/Seoul"},
    {"code": "XSES", "name": "Singapore Exchange", "country_code": "SG", "currency": "SGD", "timezone": "Asia/Singapore"},
    {"code": "XASX", "name": "Australian Securities Exchange", "country_code": "AU", "currency": "AUD", "timezone": "Australia/Sydney"},
    {"code": "XTAE", "name": "Tel Aviv Stock Exchange", "country_code": "IL", "currency": "ILS", "timezone": "Asia/Jerusalem"},
]


def seed_markets() -> int:
    """Inserta los mercados que falten; idempotente y sin tocar los existentes."""

    with session_scope() as session:
        existing = {
            code
            for code in session.execute(select(Market.code)).scalars().all()
        }
        created = 0
        for market in MARKETS:
            if market["code"] in existing:
                continue
            session.add(Market(**market, status="active"))
            created += 1
        return created
