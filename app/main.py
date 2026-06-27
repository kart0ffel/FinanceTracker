from collections import defaultdict
from datetime import date, datetime
from typing import Optional

from fastapi import FastAPI, Request, Depends, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.database import init_db, get_session, engine
from app.models import Account, Balance, ExchangeRate
from app.fx import get_or_fetch_rate, set_manual_rate, get_available_currencies, BASE_CURRENCY

app = FastAPI(title="Ledger")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


@app.on_event("startup")
def on_startup():
    init_db()
    with Session(engine) as session:
        if not session.exec(select(Account)).first():
            defaults = [
                Account(name="Main Checking", currency=BASE_CURRENCY, account_type="checking", sort_order=0),
                Account(name="Savings", currency=BASE_CURRENCY, account_type="savings", sort_order=1),
            ]
            session.add_all(defaults)
            session.commit()


ACCOUNT_TYPES = ["checking", "savings", "investment", "crypto", "other"]
ACCOUNT_TYPE_COLORS = {
    "checking": "#7FA3C9",
    "savings": "#7FA37F",
    "investment": "#C9A45C",
    "crypto": "#B58CC9",
    "other": "#9A9488",
}


def fmt_amount(value: float) -> str:
    return f"{value:,.2f}"


templates.env.filters["fmt_amount"] = fmt_amount


# ---------- Dashboard ----------

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, session: Session = Depends(get_session)):
    accounts = session.exec(
        select(Account).where(Account.is_archived == False).order_by(Account.sort_order)
    ).all()

    # latest balance per account
    latest_balances = {}
    for acc in accounts:
        stmt = (
            select(Balance)
            .where(Balance.account_id == acc.id)
            .order_by(Balance.entry_date.desc())
        )
        bal = session.exec(stmt).first()
        if bal:
            latest_balances[acc.id] = bal

    # convert each to base currency
    total_base = 0.0
    account_rows = []
    by_type_totals = defaultdict(float)
    by_currency_totals = defaultdict(float)
    fx_missing = []

    for acc in accounts:
        bal = latest_balances.get(acc.id)
        if not bal:
            continue
        rate = await get_or_fetch_rate(session, acc.currency, bal.entry_date)
        converted = bal.amount * rate if rate else None
        if converted is not None:
            total_base += converted
            by_type_totals[acc.account_type] += converted
        elif acc.currency != BASE_CURRENCY:
            fx_missing.append(acc.name)
        by_currency_totals[acc.currency] += bal.amount
        account_rows.append({
            "account": acc,
            "balance": bal,
            "converted": converted,
            "color": ACCOUNT_TYPE_COLORS.get(acc.account_type, "#9A9488"),
        })

    # net worth history: sum of all accounts' balances (converted) per distinct date
    all_balances = session.exec(
        select(Balance).join(Account).where(Account.is_archived == False).order_by(Balance.entry_date)
    ).all()

    dates_map = defaultdict(dict)  # date -> {account_id: amount}
    for b in all_balances:
        dates_map[b.entry_date][b.account_id] = b.amount

    # forward-fill: for each snapshot date, use latest known balance per account up to that date
    sorted_dates = sorted(dates_map.keys())
    history = []
    running = {}
    for d in sorted_dates:
        running.update(dates_map[d])
        total = 0.0
        for acc_id, amount in running.items():
            acc = next((a for a in accounts if a.id == acc_id), None)
            if not acc:
                continue
            rate = await get_or_fetch_rate(session, acc.currency, d)
            if rate:
                total += amount * rate
        history.append({"date": d.isoformat(), "total": round(total, 2)})

    prev_total = history[-2]["total"] if len(history) >= 2 else None
    delta = round(total_base - prev_total, 2) if prev_total is not None else None

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "total_base": round(total_base, 2),
        "base_currency": BASE_CURRENCY,
        "account_rows": account_rows,
        "history": history,
        "delta": delta,
        "by_type_totals": dict(by_type_totals),
        "by_currency_totals": dict(by_currency_totals),
        "type_colors": ACCOUNT_TYPE_COLORS,
        "has_accounts": len(accounts) > 0,
        "fx_missing": fx_missing,
    })


# ---------- Entry form ----------

@app.get("/entry", response_class=HTMLResponse)
async def entry_form(request: Request, session: Session = Depends(get_session)):
    accounts = session.exec(
        select(Account).where(Account.is_archived == False).order_by(Account.sort_order)
    ).all()

    prefill = {}
    for acc in accounts:
        stmt = (
            select(Balance)
            .where(Balance.account_id == acc.id)
            .order_by(Balance.entry_date.desc())
        )
        last = session.exec(stmt).first()
        if last:
            prefill[acc.id] = last.amount

    return templates.TemplateResponse("entry.html", {
        "request": request,
        "accounts": accounts,
        "today": date.today().isoformat(),
        "prefill": prefill,
        "saved": False,
    })


@app.post("/entry", response_class=HTMLResponse)
async def entry_submit(request: Request, session: Session = Depends(get_session)):
    form = await request.form()
    entry_date_str = form.get("entry_date")
    entry_date = date.fromisoformat(entry_date_str) if entry_date_str else date.today()

    accounts = session.exec(select(Account).where(Account.is_archived == False)).all()
    saved_count = 0
    for acc in accounts:
        field_name = f"amount_{acc.id}"
        if field_name in form and form[field_name] != "":
            amount = float(form[field_name])
            existing = session.exec(
                select(Balance).where(
                    Balance.account_id == acc.id,
                    Balance.entry_date == entry_date,
                )
            ).first()
            if existing:
                existing.amount = amount
                session.add(existing)
            else:
                session.add(Balance(account_id=acc.id, entry_date=entry_date, amount=amount))
            saved_count += 1
            # warm the FX cache for this date/currency so dashboard load is fast
            await get_or_fetch_rate(session, acc.currency, entry_date)
    session.commit()

    return RedirectResponse(url="/?saved=1", status_code=303)


# ---------- Accounts management ----------

@app.get("/accounts", response_class=HTMLResponse)
async def accounts_page(request: Request, session: Session = Depends(get_session)):
    accounts = session.exec(select(Account).order_by(Account.is_archived, Account.sort_order)).all()
    currencies = await get_available_currencies()
    return templates.TemplateResponse("accounts.html", {
        "request": request,
        "accounts": accounts,
        "account_types": ACCOUNT_TYPES,
        "currencies": currencies,
        "base_currency": BASE_CURRENCY,
    })


@app.post("/accounts/create")
async def create_account(
    name: str = Form(...),
    currency: str = Form(...),
    account_type: str = Form(...),
    session: Session = Depends(get_session),
):
    max_sort = session.exec(select(Account)).all()
    sort_order = (max(a.sort_order for a in max_sort) + 1) if max_sort else 0
    session.add(Account(name=name, currency=currency.upper(), account_type=account_type, sort_order=sort_order))
    session.commit()
    return RedirectResponse(url="/accounts", status_code=303)


@app.post("/accounts/{account_id}/archive")
async def archive_account(account_id: int, session: Session = Depends(get_session)):
    acc = session.get(Account, account_id)
    if acc:
        acc.is_archived = not acc.is_archived
        session.add(acc)
        session.commit()
    return RedirectResponse(url="/accounts", status_code=303)


@app.post("/accounts/{account_id}/delete")
async def delete_account(account_id: int, session: Session = Depends(get_session)):
    acc = session.get(Account, account_id)
    if acc:
        balances = session.exec(select(Balance).where(Balance.account_id == account_id)).all()
        for b in balances:
            session.delete(b)
        session.delete(acc)
        session.commit()
    return RedirectResponse(url="/accounts", status_code=303)


# ---------- History ----------

@app.get("/history", response_class=HTMLResponse)
async def history_page(request: Request, session: Session = Depends(get_session)):
    balances = session.exec(
        select(Balance).join(Account).order_by(Balance.entry_date.desc())
    ).all()
    accounts_by_id = {a.id: a for a in session.exec(select(Account)).all()}

    rows = [{"balance": b, "account": accounts_by_id.get(b.account_id)} for b in balances]
    return templates.TemplateResponse("history.html", {
        "request": request,
        "rows": rows,
    })


@app.post("/history/{balance_id}/delete")
async def delete_balance(balance_id: int, session: Session = Depends(get_session)):
    bal = session.get(Balance, balance_id)
    if bal:
        session.delete(bal)
        session.commit()
    return RedirectResponse(url="/history", status_code=303)


@app.post("/history/{balance_id}/edit")
async def edit_balance(balance_id: int, amount: float = Form(...), session: Session = Depends(get_session)):
    bal = session.get(Balance, balance_id)
    if bal:
        bal.amount = amount
        session.add(bal)
        session.commit()
    return RedirectResponse(url="/history", status_code=303)


# ---------- FX rate overrides ----------

@app.post("/fx/override")
async def fx_override(
    currency: str = Form(...),
    rate_date: str = Form(...),
    rate: float = Form(...),
    session: Session = Depends(get_session),
):
    set_manual_rate(session, currency.upper(), date.fromisoformat(rate_date), rate)
    return RedirectResponse(url="/accounts", status_code=303)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
