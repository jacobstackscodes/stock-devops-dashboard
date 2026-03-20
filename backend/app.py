# app.py (updated: robust raw-feature iterative forecasting with fallback)
from flask import Flask, render_template, request, jsonify
import mysql.connector
import yfinance as yf
from datetime import date, timedelta, datetime
import os
import traceback
import logging
import threading
import time
import pandas as pd
import numpy as np
import pickle

# For loading Keras model
import tensorflow as tf
from tensorflow.keras.models import load_model

# logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("stock_app")

app = Flask(__name__)

# DB config (env-friendly)
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_USER = os.getenv("DB_USER", "root")
DB_PASS = os.getenv("DB_PASS", "admin")
DB_NAME = os.getenv("DB_NAME", "stock_project")

def get_db_connection():
    return mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASS,
        database=DB_NAME,
        connection_timeout=10
    )

_live_price_cache = {}
_live_price_lock = threading.Lock()
LIVE_PRICE_TTL_SECONDS = 15

def _normalize_price_result(result: dict):
    if not isinstance(result, dict):
        return result
    for k, v in result.items():
        if isinstance(v, dict) and "price" in v:
            try:
                if v["price"] is None:
                    pass
                else:
                    v["price"] = float(v["price"])
            except Exception:
                v["price"] = None
    return result

def _ensure_float(x):
    try:
        return float(x)
    except Exception:
        return None

@app.route("/")
def landing_page():
    return render_template("landingpage.html")

@app.route("/stocks")
def stocks_page():
    return render_template("stocks.html")

@app.route("/details")
def details_page():
    ticker = request.args.get("ticker", "AAPL")
    return render_template("details.html", ticker=ticker)

@app.route("/api/tickers")
def api_tickers():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT ticker FROM stock_ohlc ORDER BY ticker")
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        tickers = [r[0] for r in rows]
        log.info("Fetched %d tickers from DB", len(tickers))
        return jsonify({"tickers": tickers})
    except Exception as e:
        tb = traceback.format_exc()
        log.error("Error in /api/tickers: %s\n%s", e, tb)
        return jsonify({"error":"db_error", "message": str(e)}), 500

@app.route("/api/stock_data")
def stock_data():
    ticker = request.args.get("ticker")
    range_param = request.args.get("range", "ALL").upper()

    if not ticker:
        return jsonify({"error":"missing_ticker", "message":"Missing ticker parameter"}), 400

    log.info("Request for /api/stock_data ticker=%s range=%s", ticker, range_param)
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        today = date.today()
        if range_param == "1M":
            start_date = today - timedelta(days=30)
        elif range_param == "3M":
            start_date = today - timedelta(days=90)
        elif range_param == "6M":
            start_date = today - timedelta(days=180)
        elif range_param == "1Y":
            start_date = today - timedelta(days=365)
        else:
            start_date = None

        if start_date:
            cursor.execute(
                "SELECT date, open, high, low, close, volume FROM stock_ohlc WHERE ticker=%s AND date >= %s ORDER BY date",
                (ticker, start_date),
            )
        else:
            cursor.execute(
                "SELECT date, open, high, low, close, volume FROM stock_ohlc WHERE ticker=%s ORDER BY date",
                (ticker,),
            )

        rows = cursor.fetchall()

        if not rows:
            try:
                data = yf.download(ticker, period="1y", interval="1d", progress=False, threads=False, auto_adjust=False)
            except TypeError:
                data = yf.download(ticker, period="1y", interval="1d", threads=False, auto_adjust=False)
            except Exception as yf_e:
                tb = traceback.format_exc()
                cursor.close()
                conn.close()
                log.error("yfinance download failed: %s\n%s", yf_e, tb)
                return jsonify({"error":"yfinance_failed", "message": str(yf_e), "trace": tb}), 502

            if data is None or data.empty:
                cursor.close()
                conn.close()
                return jsonify({"error":"no_data", "message": f"No OHLC data found for ticker {ticker} (yfinance empty)"}), 404

            try:
                data = data.reset_index()
                insert_cursor = conn.cursor()
                insert_q = """
                    INSERT INTO stock_ohlc (ticker, date, open, high, low, close, volume)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE open=VALUES(open), high=VALUES(high), low=VALUES(low), close=VALUES(close), volume=VALUES(volume)
                """
                for _, row in data.iterrows():
                    try:
                        dt = row["Date"].date() if hasattr(row["Date"], "date") else row["Date"]
                        insert_cursor.execute(insert_q, (
                            ticker,
                            dt,
                            float(row["Open"]),
                            float(row["High"]),
                            float(row["Low"]),
                            float(row["Close"]),
                            int(row["Volume"]),
                        ))
                    except Exception:
                        continue
                conn.commit()
                insert_cursor.close()
            except Exception as ins_e:
                tb = traceback.format_exc()
                cursor.close()
                conn.close()
                log.error("DB insert failed: %s\n%s", ins_e, tb)
                return jsonify({"error":"db_insert_failed", "message": str(ins_e), "trace": tb}), 500

            cursor.execute(
                "SELECT date, open, high, low, close, volume FROM stock_ohlc WHERE ticker=%s ORDER BY date",
                (ticker,),
            )
            rows = cursor.fetchall()

        cursor.close()
        conn.close()

        df = pd.DataFrame(rows)
        if not df.empty:
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date').reset_index(drop=True)
            df['close'] = pd.to_numeric(df['close'], errors='coerce')
            df['sma_10'] = df['close'].rolling(window=10, min_periods=1).mean()
            df['sma_30'] = df['close'].rolling(window=30, min_periods=1).mean()

            out = []
            for _, r in df.iterrows():
                out.append({
                    "date": r['date'].strftime("%Y-%m-%d"),
                    "open": _ensure_float(r['open']),
                    "high": _ensure_float(r['high']),
                    "low": _ensure_float(r['low']),
                    "close": _ensure_float(r['close']),
                    "volume": int(r['volume']) if r['volume'] is not None else 0,
                    "SMA_10": _ensure_float(r['sma_10']),
                    "SMA_30": _ensure_float(r['sma_30'])
                })
            return jsonify(out)
        else:
            return jsonify([])

    except Exception as e:
        tb = traceback.format_exc()
        log.error("Unexpected error in /api/stock_data: %s\n%s", e, tb)
        return jsonify({"error":"unexpected", "message": str(e), "trace": tb}), 500

@app.route("/api/live_price")
def live_price():
    ticker = request.args.get("ticker")
    if not ticker:
        return jsonify({"error":"missing_ticker", "message":"Missing ticker parameter"}), 400

    ticker = ticker.upper().strip()

    with _live_price_lock:
        cached = _live_price_cache.get(ticker)
        if cached:
            price, ts = cached
            if time.time() - ts < LIVE_PRICE_TTL_SECONDS:
                try:
                    price = float(price)
                except Exception:
                    price = None
                return jsonify({"ticker": ticker, "price": price, "cached": True})

    try:
        stock = yf.Ticker(ticker)
        try:
            hist = stock.history(period="1d")
        except TypeError:
            hist = stock.history(period="1d")
        if hist is None or hist.empty:
            log.warning("live_price: yfinance returned empty for %s", ticker)
            return jsonify({"error":"no_price", "message":"No price returned by yfinance"}), 404

        price_val = float(hist["Close"].iloc[-1])

        with _live_price_lock:
            _live_price_cache[ticker] = (price_val, time.time())

        try:
            price_json = float(round(price_val, 2))
        except Exception:
            price_json = None

        return jsonify({"ticker": ticker, "price": price_json, "cached": False})

    except Exception as e:
        tb = traceback.format_exc()
        log.error("Error fetching live price for %s: %s\n%s", ticker, e, tb)
        return jsonify({"error":"yfinance_error", "message": str(e), "trace": tb}), 500

@app.route("/api/prices")
def prices_batch():
    q = request.args.get("tickers", "")
    if not q:
        return jsonify({"error":"missing_tickers", "message":"Provide tickers=comma,separated"}), 400

    requested = [t.strip().upper() for t in q.split(",") if t.strip()]
    result = {}
    to_fetch = []

    nowt = time.time()
    with _live_price_lock:
        for t in requested:
            cached = _live_price_cache.get(t)
            if cached and nowt - cached[1] < LIVE_PRICE_TTL_SECONDS:
                try:
                    price_py = float(cached[0])
                except Exception:
                    price_py = None
                result[t] = {"price": price_py, "cached": True}
            else:
                to_fetch.append(t)

    if not to_fetch:
        _normalize_price_result(result)
        return jsonify(result)

    try:
        try:
            df = yf.download(to_fetch, period="1d", interval="1d", group_by='ticker', progress=False, threads=False)
        except TypeError:
            df = yf.download(to_fetch, period="1d", interval="1d", group_by='ticker', threads=False)
        if df is None or df.empty:
            log.warning("Batch yf.download returned empty. Falling back to individual fetch.")
            for t in to_fetch:
                try:
                    stk = yf.Ticker(t)
                    hist = stk.history(period="1d")
                    if hist is None or hist.empty:
                        result[t] = {"error": "no_price"}
                        continue
                    val = float(hist["Close"].iloc[-1])
                    result[t] = {"price": round(val,2), "cached": False}
                    with _live_price_lock:
                        _live_price_cache[t] = (val, time.time())
                except Exception as e:
                    result[t] = {"error":"fetch_failed", "message": str(e)}
            for k,v in result.items():
                if isinstance(v.get("price"), (np.generic, np.number)):
                    v["price"] = float(v["price"])
            _normalize_price_result(result)
            return jsonify(result)

        if isinstance(df.columns, pd.MultiIndex):
            for t in to_fetch:
                try:
                    if t in df.columns.levels[0]:
                        sub = df[t]
                        if 'Close' in sub.columns and not sub['Close'].dropna().empty:
                            last_close = sub['Close'].dropna().iloc[-1]
                            val = float(last_close)
                            result[t] = {"price": round(val,2), "cached": False}
                            with _live_price_lock:
                                _live_price_cache[t] = (val, time.time())
                        else:
                            result[t] = {"error":"no_price"}
                    else:
                        stk = yf.Ticker(t)
                        hist = stk.history(period="1d")
                        if hist is None or hist.empty:
                            result[t] = {"error":"no_price"}
                        else:
                            val = float(hist["Close"].iloc[-1])
                            result[t] = {"price": round(val,2), "cached": False}
                            with _live_price_lock:
                                _live_price_cache[t] = (val, time.time())
                except Exception as e:
                    result[t] = {"error":"fetch_failed", "message": str(e)}
        else:
            if 'Close' in df.columns:
                try:
                    last_close = df['Close'].dropna().iloc[-1]
                    val = float(last_close)
                    for t in to_fetch:
                        result[t] = {"price": round(val,2), "cached": False}
                        with _live_price_lock:
                            _live_price_cache[t] = (val, time.time())
                except Exception as e:
                    for t in to_fetch:
                        result[t] = {"error":"fetch_failed", "message": str(e)}
            else:
                for t in to_fetch:
                    try:
                        stk = yf.Ticker(t)
                        hist = stk.history(period="1d")
                        if hist is None or hist.empty:
                            result[t] = {"error":"no_price"}
                        else:
                            val = float(hist["Close"].iloc[-1])
                            result[t] = {"price": round(val,2), "cached": False}
                            with _live_price_lock:
                                _live_price_cache[t] = (val, time.time())
                    except Exception as e:
                        result[t] = {"error":"fetch_failed", "message": str(e)}

        for k,v in result.items():
            if "price" in v and isinstance(v["price"], (np.generic, np.number)):
                v["price"] = float(v["price"])

        _normalize_price_result(result)
        return jsonify(result)

    except Exception as e:
        tb = traceback.format_exc()
        log.error("Batch price fetch failed: %s\n%s", e, tb)
        for t in to_fetch:
            try:
                stk = yf.Ticker(t)
                hist = stk.history(period="1d")
                if hist is None or hist.empty:
                    result[t] = {"error":"no_price"}
                    continue
                val = float(hist["Close"].iloc[-1])
                result[t] = {"price": round(val,2), "cached": False}
                with _live_price_lock:
                    _live_price_cache[t] = (val, time.time())
            except Exception as e2:
                result[t] = {"error":"fetch_failed", "message": str(e2)}
        for k,v in result.items():
            if "price" in v and isinstance(v["price"], (np.generic, np.number)):
                v["price"] = float(v["price"])
        _normalize_price_result(result)
        return jsonify(result)

# -----------------------------
# Prediction endpoint (robust raw-feature iterative forecast with fallback)
# -----------------------------
def _load_model_and_scaler_for_ticker(ticker):
    base = os.path.join("models", f"{ticker}_lstm.h5")
    scal_path = os.path.join("models", f"{ticker}_scalers.pkl")
    if not os.path.exists(base) or not os.path.exists(scal_path):
        raise FileNotFoundError("Model or scaler file missing for ticker: " + ticker)
    model = load_model(base, compile=False)
    with open(scal_path, "rb") as f:
        saved = pickle.load(f)
    scaler = saved.get("scaler")
    meta = saved.get("meta", {})
    return model, scaler, meta

def _make_features_from_df(df):
    df2 = df.copy()
    df2['prev_close'] = df2['close'].shift(1)
    df2['daily_return'] = (df2['close'] / df2['prev_close']) - 1.0
    df2['range_pct'] = (df2['high'] - df2['low']) / (df2['open'] + 1e-9)
    df2['sma_5'] = df2['close'].rolling(window=5, min_periods=1).mean()
    df2['sma_10'] = df2['close'].rolling(window=10, min_periods=1).mean()
    df2['target_close'] = df2['close'].shift(-1)
    df2 = df2.dropna(subset=['open','high','low','close','volume']).reset_index(drop=True)
    return df2

@app.route("/api/predictions")
def api_predictions():
    ticker = request.args.get("ticker", "").strip().upper()
    days = int(request.args.get("days", "7"))

    if not ticker:
        return jsonify({"error":"missing_ticker", "message":"Provide ?ticker=..."}), 400
    if days <= 0 or days > 30:
        days = 7

    try:
        model, scaler, meta = _load_model_and_scaler_for_ticker(ticker)
    except FileNotFoundError as fe:
        return jsonify({"error":"model_not_found", "message": str(fe)}), 404
    except Exception as e:
        tb = traceback.format_exc()
        log.error("Failed loading model/scaler: %s\n%s", e, tb)
        return jsonify({"error":"model_load_failed", "message": str(e), "trace": tb}), 500

    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT date, open, high, low, close, volume FROM stock_ohlc WHERE ticker=%s ORDER BY date", (ticker,))
        rows = cur.fetchall()
        cur.close()
        conn.close()

        if not rows:
            return jsonify({"error":"no_data", "message": f"No rows in DB for {ticker}"}), 404

        df = pd.DataFrame(rows)
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date').reset_index(drop=True)

        for col in ['open','high','low','close','volume']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').astype(float)

        last_actual_close = float(df['close'].iloc[-1])

        df_feat = _make_features_from_df(df)

        feature_cols = meta.get('feature_cols') or ['close','open','high','low','volume','daily_return','range_pct','sma_5','sma_10']
        window_size = int(meta.get('window_size', 30))

        if len(df_feat) < window_size:
            return jsonify({"error":"not_enough_data", "message": f"Need at least {window_size} rows after feature creation"}), 400

        # last raw window (unscaled) used to build realistic next raw rows
        last_window_raw = df_feat[feature_cols].values[-window_size:].astype(np.float32)

        # initial scaled window to feed model
        try:
            scaled_window = scaler.transform(last_window_raw)
        except Exception as e:
            tb = traceback.format_exc()
            log.error("Scaler transform failed: %s\n%s", e, tb)
            return jsonify({"error":"scaler_transform_failed", "message": str(e), "trace": tb}), 500

        # index of close feature
        try:
            close_col_index = int(feature_cols.index('close')) if 'close' in feature_cols else 0
        except Exception:
            close_col_index = 0

        predictions = []
        last_date = df['date'].iloc[-1]
        hist_list = []
        hist_n = max(60, window_size)
        hist_df = df[['date','close']].copy().tail(hist_n)
        for _, r in hist_df.iterrows():
            hist_list.append({"date": r['date'].strftime("%Y-%m-%d"), "close": _ensure_float(r['close'])})

        # We'll iterate and prefer constructing new *raw* rows (realistic feature updates),
        # then re-scale them for the next step. If scaling fails, fallback to scaled-append.
        cur_scaled_window = scaled_window.copy()
        cur_raw_window = last_window_raw.copy()

        def invert_scaled_close(scaled_val, scaler_obj, col_index=0):
            try:
                if hasattr(scaler_obj, "scale_") and hasattr(scaler_obj, "min_"):
                    scale = float(scaler_obj.scale_[col_index])
                    minv = float(scaler_obj.min_[col_index])
                    if abs(scale) < 1e-12:
                        raise ValueError("scale too small for safe inversion")
                    return float((scaled_val - minv) / scale)
                if hasattr(scaler_obj, "inverse_transform"):
                    n_features = cur_scaled_window.shape[1]
                    dummy = np.zeros((1, n_features), dtype=np.float32)
                    dummy[0, col_index] = scaled_val
                    inv = scaler_obj.inverse_transform(dummy)
                    return float(inv[0, col_index])
            except Exception as e:
                log.error("invert_scaled_close error: %s", e)
                try:
                    if hasattr(scaler_obj, "inverse_transform"):
                        n_features = cur_scaled_window.shape[1]
                        dummy = np.zeros((1, n_features), dtype=np.float32)
                        dummy[0, col_index] = scaled_val
                        inv = scaler_obj.inverse_transform(dummy)
                        return float(inv[0, col_index])
                except Exception as e2:
                    log.error("invert_scaled_close fallback failed: %s", e2)
            return None

        for i in range(days):
            inp = np.expand_dims(cur_scaled_window, axis=0)
            scaled_pred = model.predict(inp, verbose=0).reshape(-1)[0]

            # get raw predicted price for display
            pred_price = invert_scaled_close(scaled_pred, scaler, col_index=close_col_index)

            next_date = last_date + timedelta(days=1)
            last_date = next_date

            predictions.append({"date": next_date.strftime("%Y-%m-%d"), "pred_close": _ensure_float(pred_price)})

            ### Preferred path: build realistic *raw* next-row and re-scale ###
            try:
                # prev close raw (from raw window)
                prev_close_raw = float(cur_raw_window[-1, close_col_index])
                last_vol_raw = float(cur_raw_window[-1, feature_cols.index('volume')]) if 'volume' in feature_cols else 0.0

                # compute raw features for new row
                new_close_raw = pred_price if pred_price is not None else prev_close_raw
                new_open_raw = new_close_raw
                new_high_raw = max(new_close_raw, prev_close_raw)
                new_low_raw = min(new_close_raw, prev_close_raw)
                new_vol_raw = last_vol_raw

                # compute raw sma values from raw closes
                raw_closes_seq = np.append(cur_raw_window[:, close_col_index], new_close_raw)
                sma_5_raw = float(np.mean(raw_closes_seq[-5:])) if raw_closes_seq.size >= 1 else float(new_close_raw)
                sma_10_raw = float(np.mean(raw_closes_seq[-10:])) if raw_closes_seq.size >= 1 else float(new_close_raw)

                # daily return
                try:
                    daily_return_raw = (new_close_raw / prev_close_raw - 1.0) if prev_close_raw != 0 else 0.0
                except Exception:
                    daily_return_raw = 0.0

                # range_pct approx
                range_pct_raw = (new_high_raw - new_low_raw) / (new_open_raw + 1e-9)

                # Compose raw new row in order of feature_cols
                new_raw_row = []
                for col in feature_cols:
                    if col == 'close':
                        new_raw_row.append(float(new_close_raw))
                    elif col == 'open':
                        new_raw_row.append(float(new_open_raw))
                    elif col == 'high':
                        new_raw_row.append(float(new_high_raw))
                    elif col == 'low':
                        new_raw_row.append(float(new_low_raw))
                    elif col == 'volume':
                        new_raw_row.append(float(new_vol_raw))
                    elif col == 'daily_return':
                        new_raw_row.append(float(daily_return_raw))
                    elif col == 'range_pct':
                        new_raw_row.append(float(range_pct_raw))
                    elif col == 'sma_5':
                        new_raw_row.append(float(sma_5_raw))
                    elif col == 'sma_10':
                        new_raw_row.append(float(sma_10_raw))
                    else:
                        # default fallback: repeat last known raw value for unknown feature
                        idx = feature_cols.index(col) if col in feature_cols else None
                        if idx is not None:
                            new_raw_row.append(float(cur_raw_window[-1, idx]))
                        else:
                            new_raw_row.append(0.0)

                new_raw_row = np.array(new_raw_row, dtype=np.float32)

                # attempt to scale the new raw row via scaler.transform
                try:
                    new_scaled_row = scaler.transform(new_raw_row.reshape(1, -1)).reshape(-1)
                    # append raw and scaled to windows
                    cur_raw_window = np.vstack([cur_raw_window, new_raw_row])[-window_size:]
                    cur_scaled_window = np.vstack([cur_scaled_window, new_scaled_row])[-window_size:]
                    continue  # continue forecasting loop
                except Exception as scale_err:
                    log.warning("Scaling new raw row failed (falling back to scaled-append): %s", scale_err)
                    # fall through to scaled append fallback below
            except Exception as e:
                log.warning("Failed building/scaling raw new row, falling back: %s", e)

            ### Fallback: append scaled_pred into scaled window (safe) ###
            try:
                fallback_new_scaled = cur_scaled_window[-1].copy()
                if np.isfinite(scaled_pred):
                    fallback_new_scaled[close_col_index] = float(scaled_pred)
                else:
                    fallback_new_scaled[close_col_index] = float(cur_scaled_window[-1, close_col_index])
                cur_scaled_window = np.vstack([cur_scaled_window, fallback_new_scaled])[-window_size:]
                # also update raw window by repeating last raw row (so raw window length preserved)
                cur_raw_window = np.vstack([cur_raw_window, cur_raw_window[-1].copy()])[-window_size:]
            except Exception as e:
                log.error("Fallback append failed: %s", e)
                break

        # summary calculation
        sumPct = 0.0
        count = 0
        increases = 0
        decreases = 0
        for p in predictions:
            pc = p.get("pred_close")
            if pc is None:
                continue
            try:
                pct = ((pc - last_actual_close) / last_actual_close) * 100.0
                sumPct += pct
                count += 1
                if pct >= 0:
                    increases += 1
                else:
                    decreases += 1
            except Exception:
                continue

        if count == 0:
            summary_text = "No numeric predictions available."
        else:
            avgPct = sumPct / count
            direction = 'stable'
            if avgPct > 0.3:
                direction = 'upward'
            elif avgPct < -0.3:
                direction = 'downward'
            summary_text = f"Model predicts a {direction} short-term trend: {avgPct:+.2f}% (avg change over {count} days)."
            if increases > decreases:
                summary_text += f" ({increases}/{count} days predicted ↑)."
            elif decreases > increases:
                summary_text += f" ({decreases}/{count} days predicted ↓)."

        out_of_range = False
        scaler_min = None
        scaler_max = None
        try:
            if hasattr(scaler, "data_min_") and hasattr(scaler, "data_max_"):
                scaler_min = float(scaler.data_min_[close_col_index])
                scaler_max = float(scaler.data_max_[close_col_index])
                if last_actual_close < scaler_min or last_actual_close > scaler_max:
                    out_of_range = True
        except Exception:
            pass

        response = {
            "historical": hist_list,
            "predictions": predictions,
            "last_actual_close": _ensure_float(last_actual_close),
            "summary": summary_text,
            "out_of_training_range": bool(out_of_range),
        }
        if scaler_min is not None and scaler_max is not None:
            response["scaler_range"] = {"min": scaler_min, "max": scaler_max}

        try:
            if hasattr(scaler, "scale_"):
                log.info("scaler.scale_[close_index]=%s", getattr(scaler, "scale_")[close_col_index])
            if hasattr(scaler, "min_"):
                log.info("scaler.min_[close_index]=%s", getattr(scaler, "min_")[close_col_index])
            if hasattr(scaler, "data_min_") and hasattr(scaler, "data_max_"):
                log.info("scaler.data_min/max close idx: %s / %s", getattr(scaler, "data_min_")[close_col_index], getattr(scaler, "data_max_")[close_col_index])
        except Exception:
            pass

        return jsonify(response)

    except Exception as e:
        tb = traceback.format_exc()
        log.error("Error in /api/predictions for %s: %s\n%s", ticker, e, tb)
        return jsonify({"error":"unexpected", "message": str(e), "trace": tb}), 500

if __name__ == "__main__":
    log.info("Starting Flask app (predictions endpoint)")
    app.run(debug=True, host="0.0.0.0", port=5000)
