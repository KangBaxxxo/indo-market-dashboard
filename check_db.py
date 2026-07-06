import sqlite3
import pandas as pd

conn = sqlite3.connect("data/market.db")

df = pd.read_sql("SELECT * FROM daily_prices LIMIT 10", conn)

print(df.columns.tolist())

print(df.head())

conn.close()