"""
lstm_model.py

Train a simple LSTM to predict next-day closing price for a given ticker
using OHLCV data from MySQL table `stock_ohlc`.

Usage:
    python lstm_model.py --ticker AAPL --window 30 --epochs 40

Outputs:
    - saved Keras model (models/<ticker>_lstm.h5)
    - scalers saved (models/<ticker>_scalers.pkl)
    - plots saved (models/<ticker>_predictions.png)
    - printed test metrics (RMSE, MAPE) and baseline comparison
"""

import os
import argparse
import pickle
from datetime import datetime

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import mysql.connector
from sklearn.preprocessing import MinMaxScaler
from sklearn.metrics import mean_squared_error, mean_absolute_percentage_error

import tensorflow as tf
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import LSTM, Dense, Dropout
from tensorflow.keras.callbacks import EarlyStopping, ModelCheckpoint

# ----------------------------
# -------- Utilities ---------
# ----------------------------
def get_db_connection(host="localhost", user="root", password="admin", database="stock_project"):
    return mysql.connector.connect(host=host, user=user, password=password, database=database)

def load_ohlcv_from_db(ticker, db_cfg=None):
    """
    Load OHLCV for ticker from MySQL table 'stock_ohlc'.
    Returns a pandas DataFrame with columns: date, open, high, low, close, volume
    Sorted by date ascending.
    """
    if db_cfg is None:
        db_cfg = {}
    conn = get_db_connection(**db_cfg)
    query = """
        SELECT date, open, high, low, close, volume
        FROM stock_ohlc
        WHERE ticker = %s
        ORDER BY date ASC
    """
    df = pd.read_sql(query, conn, params=(ticker,))
    conn.close()
    if df.empty:
        raise ValueError(f"No data found for ticker {ticker}")
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)
    return df

def create_features(df):
    """
    Create features for the model from OHLCV DataFrame.
    Returns DataFrame with features and target column 'target_close' (next day's close).
    """
    df2 = df.copy()
    df2['prev_close'] = df2['close'].shift(1)
    df2['daily_return'] = (df2['close'] / df2['prev_close']) - 1.0
    df2['range_pct'] = (df2['high'] - df2['low']) / (df2['open'] + 1e-9)
    df2['sma_5'] = df2['close'].rolling(window=5, min_periods=1).mean()
    df2['sma_10'] = df2['close'].rolling(window=10, min_periods=1).mean()
    df2['target_close'] = df2['close'].shift(-1)
    df2 = df2.dropna(subset=['open','high','low','close','volume','target_close']).reset_index(drop=True)
    return df2

# ----------------------------
# ----- Model Building -------
# ----------------------------
def build_lstm_model(input_shape, lstm_units=64, dropout_rate=0.2):
    model = Sequential()
    model.add(LSTM(lstm_units, return_sequences=True, input_shape=input_shape))
    model.add(Dropout(dropout_rate))
    model.add(LSTM(lstm_units // 2))
    model.add(Dropout(dropout_rate))
    model.add(Dense(32, activation='relu'))
    model.add(Dense(1, activation='linear'))
    model.compile(optimizer='adam', loss='mse')
    return model

# ----------------------------
# ----- Training Pipeline -----
# ----------------------------
def train_for_ticker(ticker,
                     window_size=30,
                     epochs=40,
                     batch_size=32,
                     val_split=0.15,
                     test_split=0.15,
                     db_cfg=None,
                     out_dir='models',
                     verbose=1):
    print(f"[{datetime.now()}] Loading data for {ticker} ...")
    df = load_ohlcv_from_db(ticker, db_cfg=db_cfg)

    print(f"[{datetime.now()}] Creating features ...")
    df_feat = create_features(df)

    feature_cols = ['close', 'open', 'high', 'low', 'volume', 'daily_return', 'range_pct', 'sma_5', 'sma_10']
    data = df_feat[feature_cols].values.astype(np.float32)
    targets = df_feat['target_close'].values.astype(np.float32)

    n_total = len(data)
    test_n = int(n_total * test_split)
    val_n = int(n_total * val_split)
    train_n = n_total - val_n - test_n
    if train_n <= window_size:
        raise RuntimeError("Not enough training data relative to window size. Reduce window or gather more data.")

    train_data = data[:train_n]
    val_data = data[train_n: train_n + val_n + window_size]
    test_data = data[train_n + val_n:]

    scaler = MinMaxScaler(feature_range=(0,1))
    scaler.fit(train_data)

    data_scaled = scaler.transform(data)
    scaled_close_all = data_scaled[:, 0]

    X_all, y_all = [], []
    for i in range(len(data_scaled) - window_size):
        X_all.append(data_scaled[i:i+window_size])
        y_all.append(scaled_close_all[i + window_size])
    X_all = np.array(X_all)
    y_all = np.array(y_all)

    total_sequences = X_all.shape[0]
    train_seq_end = train_n - window_size
    val_seq_end = train_n + val_n - window_size

    if train_seq_end <= 0:
        raise RuntimeError("Not enough train sequences. Decrease window_size or get more data.")

    X_train = X_all[:train_seq_end]
    y_train = y_all[:train_seq_end]

    X_val = X_all[train_seq_end: val_seq_end]
    y_val = y_all[train_seq_end: val_seq_end]

    X_test = X_all[val_seq_end:]
    y_test = y_all[val_seq_end:]

    print(f"Total sequences: {total_sequences}, train: {len(X_train)}, val: {len(X_val)}, test: {len(X_test)}")

    input_shape = (window_size, X_train.shape[2])
    model = build_lstm_model(input_shape, lstm_units=64, dropout_rate=0.2)
    model.summary()

    os.makedirs(out_dir, exist_ok=True)
    model_path = os.path.join(out_dir, f"{ticker}_lstm.h5")
    scaler_path = os.path.join(out_dir, f"{ticker}_scalers.pkl")

    es = EarlyStopping(monitor='val_loss', patience=8, restore_best_weights=True)
    mc = ModelCheckpoint(model_path, monitor='val_loss', save_best_only=True, verbose=1)

    print(f"[{datetime.now()}] Training model ...")
    history = model.fit(
        X_train, y_train,
        validation_data=(X_val, y_val),
        epochs=epochs,
        batch_size=batch_size,
        callbacks=[es, mc],
        verbose=verbose
    )

    print(f"[{datetime.now()}] Evaluating on test set ...")
    y_pred_scaled = model.predict(X_test).reshape(-1)
    y_true_scaled = y_test.reshape(-1)

    def inverse_close(scaled_close_vals, scaler_obj):
        n = len(scaled_close_vals)
        n_features = scaler_obj.scale_.shape[0]
        dummy = np.zeros((n, n_features), dtype=np.float32)
        dummy[:, 0] = scaled_close_vals
        inv = scaler_obj.inverse_transform(dummy)
        return inv[:, 0]

    y_pred = inverse_close(y_pred_scaled, scaler)
    y_true = inverse_close(y_true_scaled, scaler)

    rmse = np.sqrt(mean_squared_error(y_true, y_pred))
    mape = mean_absolute_percentage_error(y_true, y_pred) * 100.0
    print(f"Test RMSE: {rmse:.4f}, Test MAPE: {mape:.2f}%")

    last_close_scaled = X_test[:, -1, 0]
    last_close = inverse_close(last_close_scaled, scaler)
    baseline_rmse = np.sqrt(mean_squared_error(y_true, last_close))
    baseline_mape = mean_absolute_percentage_error(y_true, last_close) * 100.0
    print(f"Baseline (last close) RMSE: {baseline_rmse:.4f}, MAPE: {baseline_mape:.2f}%")

    meta = {
        'feature_cols': feature_cols,
        'window_size': window_size,
        'ticker': ticker
    }
    with open(scaler_path, 'wb') as f:
        pickle.dump({'scaler': scaler, 'meta': meta}, f)
    print(f"Saved model to {model_path} and scalers to {scaler_path}")

    try:
        plt.figure(figsize=(12,6))
        plt.plot(y_true, label='True Close')
        plt.plot(y_pred, label='Predicted Close')
        plt.plot(last_close, label='Baseline Last-Close', alpha=0.6)
        plt.legend()
        plt.title(f"{ticker} - Test Predictions (RMSE {rmse:.3f})")
        plt.xlabel("Test samples (time order)")
        plt.ylabel("Price")
        plot_path = os.path.join(out_dir, f"{ticker}_predictions.png")
        plt.savefig(plot_path, bbox_inches='tight', dpi=150)
        print(f"Saved prediction plot to {plot_path}")
    except Exception as e:
        print("Plot saving failed:", e)

    return {
        'model': model,
        'scaler': scaler,
        'y_true': y_true,
        'y_pred': y_pred,
        'rmse': rmse,
        'mape': mape,
        'baseline_rmse': baseline_rmse,
        'baseline_mape': baseline_mape,
        'meta': meta
    }

# ----------------------------
# --------- CLI -------------
# ----------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train LSTM model for stock closing price forecasting.")
    parser.add_argument('--ticker', type=str, required=True, help='Ticker symbol (e.g., AAPL)')
    parser.add_argument('--window', type=int, default=30, help='Lookback window size (days)')
    parser.add_argument('--epochs', type=int, default=40, help='Number of training epochs')
    parser.add_argument('--batch', type=int, default=32, help='Batch size')
    parser.add_argument('--out', type=str, default='models', help='Output directory to save model and scalers')
    parser.add_argument('--db-host', type=str, default='localhost')
    parser.add_argument('--db-user', type=str, default='root')
    parser.add_argument('--db-pass', type=str, default='admin')
    parser.add_argument('--db-name', type=str, default='stock_project')

    args = parser.parse_args()

    db_cfg = {
        'host': args.db_host,
        'user': args.db_user,
        'password': args.db_pass,
        'database': args.db_name
    }

    os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'
    tf.get_logger().setLevel('ERROR')

    results = train_for_ticker(
        args.ticker.upper(),
        window_size=args.window,
        epochs=args.epochs,
        batch_size=args.batch,
        db_cfg=db_cfg,
        out_dir=args.out,
        verbose=1
    )

    print("Done.")

