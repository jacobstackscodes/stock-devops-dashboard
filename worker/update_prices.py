import datetime as dt
import mysql.connector
import yfinance as yf
import pandas as pd

DB_CFG = dict(
    host="localhost",
    user="root",
    password="admin",   # your MySQL password
    database="stock_project"
)

TICKERS = ["AAPL"]  # add more tickers if needed


def get_last_date(cur, ticker):
    """Get the last available date for a ticker in DB"""
    cur.execute("SELECT MAX(date) FROM stock_ohlc WHERE ticker=%s", (ticker,))
    return cur.fetchone()[0]


def _extract_field(row, field, ticker):
    """Return a scalar value for row[field] whether it's a scalar or a Series (multi-column df)."""
    val = row[field]
    if isinstance(val, pd.Series):
        # prefer explicit ticker column if available, otherwise first element
        if ticker in val.index:
            return val[ticker]
        return val.iloc[0]
    return val


def main():
    conn = mysql.connector.connect(**DB_CFG)
    cur = conn.cursor()

    today = dt.date.today()

    for ticker in TICKERS:
        last_date = get_last_date(cur, ticker)

        # Normalize last_date (could be None, date, datetime, or string)
        if last_date is not None:
            if isinstance(last_date, dt.datetime):
                last_date = last_date.date()
            elif not isinstance(last_date, dt.date):
                try:
                    last_date = dt.date.fromisoformat(str(last_date))
                except Exception:
                    last_date = None

        # Decide where to start fetching
        if last_date is not None:
            start_date = last_date + dt.timedelta(days=1)
        else:
            start_date = today - dt.timedelta(days=365)  # fetch last year if first run

        if start_date > today:
            print(f"{ticker}: up to date (no new days).")
            continue

        end_date = today + dt.timedelta(days=1)

        print(f"{ticker}: fetching {start_date} → {today}")
        df = yf.download(ticker, start=start_date, end=end_date, progress=False, auto_adjust=False)

        if df.empty:
            print(f"{ticker}: no rows returned (market closed or holiday).")
            continue

        # Insert / update rows
        inserted = 0
        for d, row in df.iterrows():
            close_val = _extract_field(row, "Close", ticker)
            if pd.isna(close_val):
                continue

            open_v = float(_extract_field(row, "Open", ticker))
            high_v = float(_extract_field(row, "High", ticker))
            low_v = float(_extract_field(row, "Low", ticker))
            close_v = float(close_val)
            vol_raw = _extract_field(row, "Volume", ticker)
            vol_v = int(vol_raw) if not pd.isna(vol_raw) else 0

            cur.execute(
                """
                INSERT INTO stock_ohlc (ticker, date, open, high, low, close, volume)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                  open=VALUES(open),
                  high=VALUES(high),
                  low=VALUES(low),
                  close=VALUES(close),
                  volume=VALUES(volume)
                """,
                (
                    ticker,
                    d.date() if hasattr(d, "date") else d,  # handle Timestamp or date
                    open_v,
                    high_v,
                    low_v,
                    close_v,
                    vol_v,
                ),
            )
            inserted += 1

        conn.commit()
        print(f"{ticker}: upserted {inserted} rows.")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()