from datetime import date, datetime
from typing import Optional
from sqlmodel import SQLModel, Field, Relationship


class Account(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    currency: str = Field(index=True)  # ISO code, e.g. CHF, USD, EUR
    account_type: str = Field(default="checking")  # checking, savings, investment, crypto, other
    is_archived: bool = Field(default=False)
    sort_order: int = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    balances: list["Balance"] = Relationship(back_populates="account")


class Balance(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    account_id: int = Field(foreign_key="account.id", index=True)
    entry_date: date = Field(index=True)
    amount: float
    note: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    account: Account = Relationship(back_populates="balances")


class ExchangeRate(SQLModel, table=True):
    """Cached exchange rate: 1 unit of `currency` = `rate` units of base currency, on `rate_date`."""
    id: Optional[int] = Field(default=None, primary_key=True)
    currency: str = Field(index=True)
    rate_date: date = Field(index=True)
    rate: float  # to base currency (CHF)
    is_manual_override: bool = Field(default=False)
    fetched_at: datetime = Field(default_factory=datetime.utcnow)


class Settings(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    key: str = Field(index=True, unique=True)
    value: str
