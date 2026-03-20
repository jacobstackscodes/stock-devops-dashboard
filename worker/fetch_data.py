# fetch_data.py
import mysql.connector
import yfinance as yf
from datetime import date
import os
import time
import pandas as pd

# Database Configuration
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_USER = os.getenv("DB_USER", "root")
DB_PASS = os.getenv("DB_PASS", "admin")
DB_NAME = os.getenv("DB_NAME", "stock_project")

def get_db_connection():
    return mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASS,
        database=DB_NAME
    )

# Full Ticker List (from your Stocks page)
TICKERS = [
    "AAPL", "MSFT", "GOOG", "AMZN", "TSLA",
    "META", "NFLX", "NVDA", "AMD", "INTC",
    "IBM", "ORCL", "ADBE", "CRM", "BABA",
    "V", "MA", "PYPL", "JPM", "BAC"
]

INSERT_Q = """
    INSERT INTO stock_ohlc (ticker, date, open, high, low, close, volume)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        open = VALUES(open),
        high = VALUES(high),
        low = VALUES(low),
        close = VALUES(close),
        volume = VALUES(volume)
"""

def fetch_ticker_to_df(ticker, period="1y"):
    """
    Fetch ticker OHLC data into a cleaned DataFrame with a Date column.
    """
    # Explicitly set auto_adjust to False (avoid FutureWarning surprises)
    df = yf.download(ticker, period=period, interval="1d", progress=False, auto_adjust=False, threads=False)
    if df is None or df.empty:
        return None
    df = df.reset_index()
    # Ensure a Date column of datetime64[ns]
    if 'Date' not in df.columns:
        # maybe index is already datetime; make Date from index
        df['Date'] = pd.to_datetime(df.index)
    else:
        df['Date'] = pd.to_datetime(df['Date'])
    return df

def fetch_and_store():
    conn = get_db_connection()
    cursor = conn.cursor()

    for ticker in TICKERS:
        print(f"\nFetching data for {ticker}...")
        try:
            df = fetch_ticker_to_df(ticker, period="1y")
            if df is None or df.empty:
                print(f"⚠️  No data returned for {ticker} (skipping).")
                continue

            print(f"Inserting {len(df)} rows for {ticker}...")

            inserted = 0
            for row in df.itertuples(index=False):
                # itertuples gives attributes: Date, Open, High, Low, Close, Volume (usually)
                # Be defensive: try to access attributes, fall back to indexing
                try:
                    dt = getattr(row, "Date", None)
                    if dt is None:
                        # fallback: try first field
                        dt = row[0]
                    # dt should be a pd.Timestamp or python datetime
                    # convert to date object
                    try:
                        dt_date = dt.date()
                    except Exception:
                        # if dt is numpy datetime64, use pandas to convert
                        dt_date = pd.to_datetime(dt).date()

                    # get price fields robustly
                    # common attribute names are Open, High, Low, Close, Volume
                    open_v = getattr(row, "Open", row[1] if len(row) > 1 else None)
                    high_v = getattr(row, "High", row[2] if len(row) > 2 else None)
                    low_v = getattr(row, "Low", row[3] if len(row) > 3 else None)
                    close_v = getattr(row, "Close", row[4] if len(row) > 4 else None)
                    vol_v = getattr(row, "Volume", row[5] if len(row) > 5 else 0)

                    if open_v is None or high_v is None or low_v is None or close_v is None:
                        # skip rows missing core OHLC
                        continue

                    cursor.execute(INSERT_Q, (
                        ticker,
                        dt_date,
                        float(open_v),
                        float(high_v),
                        float(low_v),
                        float(close_v),
                        int(vol_v) if not pd.isna(vol_v) else 0
                    ))
                    inserted += 1
                except Exception as row_e:
                    # print the problematic row index / snippet but continue
                    print(f"    ⚠️  skipped a row due to error: {row_e}")
                    continue

            conn.commit()
            print(f"✅ Inserted/upserted {inserted} rows for {ticker}.")

            # small delay to avoid potential throttling
            time.sleep(1.5)

        except Exception as e:
            print(f"❌ Error fetching {ticker}: {e}")
            continue

    cursor.close()
    conn.close()
    print("\n✅ All tickers processed.")

if __name__ == "__main__":
    fetch_and_store()
