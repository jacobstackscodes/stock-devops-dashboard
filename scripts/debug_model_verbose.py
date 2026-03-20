# debug_model_verbose.py
import os, pickle, argparse, numpy as np, pandas as pd
from tensorflow.keras.models import load_model
import mysql.connector

def get_db_df(ticker):
    conn = mysql.connector.connect(host='localhost', user='root', password='admin', database='stock_project')
    q = "SELECT date, open, high, low, close, volume FROM stock_ohlc WHERE ticker=%s ORDER BY date"
    df = pd.read_sql(q, conn, params=(ticker,))
    conn.close()
    return df

def main(ticker):
    ticker = ticker.upper()
    model_path = os.path.join('models', f'{ticker}_lstm.h5')
    scal_path = os.path.join('models', f'{ticker}_scalers.pkl')
    assert os.path.exists(model_path) and os.path.exists(scal_path), "model or scaler missing"

    model = load_model(model_path, compile=False)
    print("Loaded model:", model_path)

    saved = pickle.load(open(scal_path, 'rb'))
    scaler = saved.get('scaler')
    meta = saved.get('meta', {})
    print("Loaded scaler from:", scal_path)
    print("meta:", meta)

    df = get_db_df(ticker)
    # convert numeric types
    for c in ['open','high','low','close','volume']:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce').astype(float)
    print("DB rows:", len(df))
    print("Last actual close (from DB):", df['close'].iloc[-1])

    # feature columns / window
    feature_cols = meta.get('feature_cols') or ['close','open','high','low','volume','daily_return','range_pct','sma_5','sma_10']
    window = int(meta.get('window_size', 30))
    print("feature_cols (used at training):", feature_cols)
    print("window_size:", window)

    # build features identical to training
    df2 = df.copy()
    df2['prev_close'] = df2['close'].shift(1)
    df2['daily_return'] = (df2['close'] / df2['prev_close']) - 1.0
    df2['range_pct'] = (df2['high'] - df2['low']) / (df2['open'] + 1e-9)
    df2['sma_5'] = df2['close'].rolling(5, min_periods=1).mean()
    df2['sma_10'] = df2['close'].rolling(10, min_periods=1).mean()
    df2 = df2.dropna().reset_index(drop=True)

    last_window_raw = df2[feature_cols].values[-window:].astype(np.float32)
    print("last_window_raw shape:", last_window_raw.shape)
    print("last raw row (most recent):", last_window_raw[-1])

    # scale window
    try:
        scaled_window = scaler.transform(last_window_raw)
    except Exception as e:
        print("Scaler.transform FAILED:", e)
        return

    scaled_pred = model.predict(np.expand_dims(scaled_window, axis=0), verbose=0).reshape(-1)[0]
    print("scaled_pred:", scaled_pred)

    # Show scaler internals if present
    if hasattr(scaler, 'scale_'):
        print("scaler.scale_[0]:", getattr(scaler, 'scale_')[0])
    if hasattr(scaler, 'min_'):
        print("scaler.min_[0]:", getattr(scaler, 'min_')[0])
    if hasattr(scaler, 'data_min_'):
        print("scaler.data_min_[0]:", getattr(scaler, 'data_min_')[0])
    if hasattr(scaler, 'data_max_'):
        print("scaler.data_max_[0]:", getattr(scaler, 'data_max_')[0])

    # Robust inverse (scale/min) if possible
    inv_price = None
    if hasattr(scaler, 'scale_') and hasattr(scaler, 'min_'):
        scale = scaler.scale_[0]
        minv = scaler.min_[0]
        if scale != 0:
            inv_price = (scaled_pred - minv) / scale
            print("inverse via (scaled - min)/scale =>", inv_price)
    # fallback inverse_transform
    try:
        n = scaled_window.shape[1]
        dummy = np.zeros((1, n), dtype=np.float32)
        dummy[0, 0] = scaled_pred
        inv_fallback = scaler.inverse_transform(dummy)[0,0]
        print("inverse via scaler.inverse_transform fallback =>", inv_fallback)
    except Exception as e:
        print("fallback inverse_transform failed:", e)

if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--ticker', required=True)
    args = p.parse_args()
    main(args.ticker)
