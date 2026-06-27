# Ledger — Personal Net Worth Tracker

A small, self-hosted app for tracking your account balances over time and
seeing your net worth in one currency (CHF by default), even across accounts
held in different currencies.

## How it works

1. Every period (e.g. last day of the month), open the app and go to
   **Add Entry**. Enter the current balance for each of your accounts.
2. The **Dashboard** shows your total net worth, converted to your base
   currency, a trend chart over time, and a per-account breakdown.
3. Manage accounts (add, archive, delete) under **Accounts**. Each account
   has its own currency — exchange rates are fetched automatically per
   entry date and cached, so historical entries stay accurate.
4. **History** lets you review or correct past entries.

## Running it

Requires Docker and Docker Compose.

```bash
docker compose up -d --build
```

Then open **http://localhost:8000**.

Your data is stored in a Docker named volume (`ledger_data`), so it survives
container restarts and rebuilds. To back it up:

```bash
docker run --rm -v ledger_data:/data -v $(pwd):/backup alpine \
  cp /data/finance.db /backup/finance-backup.db
```

To stop the app:

```bash
docker compose down
```

(This keeps the volume. Add `-v` to also delete stored data.)

## Configuration

- **Base currency**: currently hardcoded to `CHF` in `app/fx.py`
  (`BASE_CURRENCY`). Change this constant and rebuild if you want a
  different base currency.
- **Exchange rates**: fetched from [Frankfurter](https://frankfurter.dev/)
  (ECB-backed, free, no API key) and cached per currency/date in the
  database. If the API is unreachable, the dashboard will flag affected
  accounts with "rate unavailable" rather than silently mis-stating your
  net worth — you can set a rate manually under **Accounts → Exchange
  rate override**.

## Project structure

```
app/
  main.py          FastAPI routes
  models.py        SQLModel table definitions (Account, Balance, ExchangeRate)
  database.py      SQLite engine + session setup
  fx.py            Exchange rate fetching/caching logic
  templates/       Jinja2 HTML templates
  static/style.css Styling
Dockerfile
docker-compose.yml
requirements.txt
```

## Notes on the data model

- `Account`: name, currency, type (checking/savings/investment/crypto/other)
- `Balance`: one row per account per entry date — a point-in-time snapshot,
  not a transaction ledger. This app tracks balances, not individual
  transactions.
- `ExchangeRate`: cached rate (1 unit of currency → base currency) per date,
  with a flag for manual overrides so they aren't overwritten by later
  auto-fetches.

## Extending it

Some natural next steps if you want to grow this:
- Add authentication if you expose this beyond your local network.
- Add a budget/category layer on top of `Balance` if you want spending
  tracking rather than just net-worth snapshots.
- Add CSV export from the History page.
