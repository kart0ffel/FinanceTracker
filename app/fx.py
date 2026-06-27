from datetime import date
from typing import Optional
import httpx
from sqlmodel import Session, select

from app.models import ExchangeRate

BASE_CURRENCY = "CHF"
FRANKFURTER_URL = "https://api.frankfurter.app"


def get_cached_rate(session: Session, currency: str, rate_date: date) -> Optional[ExchangeRate]:
    if currency == BASE_CURRENCY:
        return ExchangeRate(currency=currency, rate_date=rate_date, rate=1.0)
    stmt = select(ExchangeRate).where(
        ExchangeRate.currency == currency,
        ExchangeRate.rate_date == rate_date,
    )
    return session.exec(stmt).first()


async def fetch_rate_from_api(currency: str, rate_date: date) -> Optional[float]:
    """Fetch historical rate: 1 `currency` = X BASE_CURRENCY, for a given date."""
    if currency == BASE_CURRENCY:
        return 1.0
    url = f"{FRANKFURTER_URL}/{rate_date.isoformat()}"
    params = {"from": currency, "to": BASE_CURRENCY}
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            return data.get("rates", {}).get(BASE_CURRENCY)
    except (httpx.HTTPError, KeyError, ValueError):
        return None


async def get_or_fetch_rate(session: Session, currency: str, rate_date: date) -> Optional[float]:
    """Returns rate (1 currency -> BASE_CURRENCY) using cache first, then API, then falls
    back to the most recent known rate for that currency if the API is unreachable."""
    if currency == BASE_CURRENCY:
        return 1.0

    cached = get_cached_rate(session, currency, rate_date)
    if cached:
        return cached.rate

    fetched = await fetch_rate_from_api(currency, rate_date)
    if fetched is not None:
        rate_obj = ExchangeRate(currency=currency, rate_date=rate_date, rate=fetched)
        session.add(rate_obj)
        session.commit()
        return fetched

    # Fallback: most recent rate we have for this currency, regardless of date
    stmt = (
        select(ExchangeRate)
        .where(ExchangeRate.currency == currency)
        .order_by(ExchangeRate.rate_date.desc())
    )
    fallback = session.exec(stmt).first()
    return fallback.rate if fallback else None


def set_manual_rate(session: Session, currency: str, rate_date: date, rate: float) -> ExchangeRate:
    existing = get_cached_rate(session, currency, rate_date)
    if existing and existing.id:
        existing.rate = rate
        existing.is_manual_override = True
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing
    rate_obj = ExchangeRate(
        currency=currency, rate_date=rate_date, rate=rate, is_manual_override=True
    )
    session.add(rate_obj)
    session.commit()
    session.refresh(rate_obj)
    return rate_obj


async def get_available_currencies() -> dict:
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(f"{FRANKFURTER_URL}/currencies")
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError:
        return {
            "CHF": "Swiss Franc", "USD": "US Dollar", "EUR": "Euro",
            "GBP": "British Pound", "JPY": "Japanese Yen",
        }
