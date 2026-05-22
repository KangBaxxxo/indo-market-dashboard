from sqlalchemy import create_engine
from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(DATABASE_URL)

try:

    with engine.connect() as conn:

        print("SUCCESS CONNECT SUPABASE 😈🔥")

except Exception as e:

    print("FAILED 😭🔥")
    print(e)