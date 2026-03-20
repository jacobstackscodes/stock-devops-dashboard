# debug_model_predict.py
import numpy as np
import pickle, os, argparse
from tensorflow.keras.models import load_model
import pandas as pd
import mysql.connector

def get_db(ticker, db_cfg={'host':'localhost','user':'root','password':'admin','database':'stock_project'}):
    conn = mysql.connector.connect(**db_cfg)
    q = "SELECT date, open, high, low, close, volume FROM stock_ohlc WHERE ticker=%s ORDER BY date"
    df = pd.read_sql(q, conn, params=(ticker,))
    conn.close()
    return df

def main(ticker):
    model_path = os.path.join('models', f'{ticker}_lstm.h5')
    scal_path = os.path.join('models', f'{ticker}_scalers.pkl')
    assert os.path.exists(model_path) and os.path.exists(scal_path), "model or scaler missing"
    model = load_model(model_path, compile=False)
    saved = pickle.load(open(scal_path,'rb'))
    scaler = saved['scaler']
    meta = saved.get('meta', {})
    window = int(meta.get('window_size', 30))
    df = get_db(ticker)
    # convert decimals -> float if needed
    for c in ['open','high','low','close','volume']:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce').astype(float)
    # build features (same as training)
    df2 = df.copy()
    df2['prev_close'] = df2['close'].shift(1)
    df2['daily_return'] = (df2['close'] / df2['prev_close']) - 1.0
    df2['range_pct'] = (df2['high'] - df2['low']) / (df2['open'] + 1e-9)
    df2['sma_5'] = df2['close'].rolling(5, min_periods=1).mean()
    df2['sma_10'] = df2['close'].rolling(10, min_periods=1).mean()
    df2 = df2.dropna().reset_index(drop=True)
    feature_cols = meta.get('feature_cols') or ['close','open','high','low','volume','daily_return','range_pct','sma_5','sma_10']
    last_raw = df2[feature_cols].values[-window:].astype(np.float32)
    scaled = scaler.transform(last_raw)
    inp = np.expand_dims(scaled, axis=0)
    scaled_pred = model.predict(inp, verbose=0).reshape(-1)[0]
    print("scaled_pred:", scaled_pred)
    # robust inverse using scaler.scale_/min_
    if hasattr(scaler, 'scale_') and hasattr(scaler, 'min_'):
        scale = scaler.scale_[0]
        minv = scaler.min_[0]
        inv = (scaled_pred - minv) / scale if scale!=0 else None
        print("inverse via scale/min:", inv)
    else:
        # fallback
        n = scaled.shape[1]
        dummy = np.zeros((1,n), dtype=np.float32)
        dummy[0,0] = scaled_pred
        invv = scaler.inverse_transform(dummy)
        print("inverse fallback:", invv[0,0])

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--ticker', required=True)
    args = p.parse_args()
    main(args.ticker.upper())
