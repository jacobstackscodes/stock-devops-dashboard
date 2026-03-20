import mysql.connector

# Connect to MySQL
conn = mysql.connector.connect(
    host="localhost",
    user="root",
    password="admin",
    database="stock_project"
)

cursor = conn.cursor()

# Check how many rows exist
cursor.execute("SELECT COUNT(*) FROM stock_ohlc")
row_count = cursor.fetchone()
print("Total rows in stock_ohlc:", row_count[0])

# Show the first 5 rows if they exist
cursor.execute("SELECT * FROM stock_ohlc LIMIT 5")
rows = cursor.fetchall()
for row in rows:
    print(row)

cursor.close()
conn.close()
