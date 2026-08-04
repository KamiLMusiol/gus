#pip install -r requirements.txt dla maca/linuxa pip3

import os
import pandas as pd
import streamlit as st
from sqlalchemy import create_engine
from dotenv import load_dotenv

load_dotenv()

db_user = os.getenv("POSTGRES_USER")
db_password = os.getenv("POSTGRES_PASSWORD")
db_name = os.getenv("POSTGRES_DB")
db_port = os.getenv("POSTGRES_PORT")

url = f"postgresql+psycopg2://{db_user}:{db_password}@localhost:{db_port}/{db_name}"
engine = create_engine(url)

st.title("Produkt krajowy brutto ogółem")

# na razie na sztywno wskaznik z arkusza1 - pozniej to sie rozszerzy o wybor wskaznika/tabeli
query = """
    SELECT r.nazwa, f.rok, f.wartosc
    FROM fakt_regionalne f
    JOIN dim_region r ON r.kod = f.kod
    JOIN dim_wskaznik w ON w.wskaznik_id = f.wskaznik_id
    WHERE w.nazwa_wskaznika = 'produkt krajowy brutto ogółem'
"""
df = pd.read_sql(query, engine)

tabela = df.pivot(index="nazwa", columns="rok", values="wartosc")

st.dataframe(tabela)