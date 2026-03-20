import mysql.connector
import pandas as pd
import matplotlib.pyplot as plt
import mplfinance as mpf

# Connect to MySQL
conn = mysql.connector.connect(
    host="localhost",
    user="root",
    password="admin",  # change if needed
    database="stock_project"
)

# Query the OHLC data
query = "SELECT date, open, high, low, close, volume FROM stock_ohlc WHERE ticker='AAPL'"
df = pd.read_sql(query, conn)

# Close connection
conn.close()

# Convert date to datetime
df['date'] = pd.to_datetime(df['date'])

# Sort by date
df = df.sort_values('date')

# Plot closing price Trend chart (closing price)
plt.figure(figsize=(12,6))
plt.plot(df['date'], df['close'], label="Closing Price", color='blue')
plt.title("AAPL Closing Price (2023)")
plt.xlabel("Date")
plt.ylabel("Price (USD)")
plt.legend()
plt.show()

#Candlestick Chart
df_mpf = df.set_index('date')   # mplfinance needs datetime index
df_mpf = df_mpf[['open','high','low','close','volume']]  # ensure correct columns

mpf.plot(df_mpf, type='candle', volume=True, style='yahoo', title="AAPL Candlestick Chart")

#Daily Returns (Percentage Change in Closing Price)
df['daily_return'] = df['close'].pct_change()

plt.figure(figsize=(12,6))
plt.plot(df['date'], df['daily_return'], label="Daily Return", color='green')
plt.axhline(0, linestyle='--', color='red')
plt.title("AAPL Daily Returns (%)")
plt.xlabel("Date")
plt.ylabel("Return")
plt.legend()
plt.show()

#Volume Traded Over Time
plt.figure(figsize=(12,6))
plt.bar(df['date'], df['volume'], color='orange')
plt.title("AAPL Trading Volume")
plt.xlabel("Date")
plt.ylabel("Volume")
plt.show()

#Moving Averages (SMA)
df['SMA_10'] = df['close'].rolling(window=10).mean()
df['SMA_30'] = df['close'].rolling(window=30).mean()

plt.figure(figsize=(12,6))
plt.plot(df['date'], df['close'], label="Closing Price", color='blue')
plt.plot(df['date'], df['SMA_10'], label="10-Day SMA", color='red')
plt.plot(df['date'], df['SMA_30'], label="30-Day SMA", color='green')
plt.title("AAPL Moving Averages")
plt.xlabel("Date")
plt.ylabel("Price (USD)")
plt.legend()
plt.show()

#Correlation: Volume vs Closing Price
plt.figure(figsize=(8,6))
plt.scatter(df['volume'], df['close'], alpha=0.5, color='purple')
plt.title("AAPL Volume vs Closing Price")
plt.xlabel("Volume")
plt.ylabel("Closing Price")
plt.show()
