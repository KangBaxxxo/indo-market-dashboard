import pandas as pd

driver = pd.read_csv("data/driver_prices.csv")

print(sorted(driver["driver"].unique()))