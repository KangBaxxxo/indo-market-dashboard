import yfinance as yf

ticker = yf.Ticker("BBCA.JK")

df = ticker.history(period="5d")

print(df)