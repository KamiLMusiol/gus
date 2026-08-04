#pip install -r requirements.txt dla maca/linexa pip3
#zalozenie tutaj jest takie ze format danych raczej sie nie zmienia

import pandas as pd
import os
import glob
from sqlalchemy import create_engine
from sqlalchemy import text

from dotenv import load_dotenv
load_dotenv()


db_user = os.getenv("POSTGRES_USER")
db_password = os.getenv("POSTGRES_PASSWORD")
db_name = os.getenv("POSTGRES_DB")
db_port = os.getenv("POSTGRES_PORT")


sql = """
    CREATE TABLE dim_region (
    kod         TEXT PRIMARY KEY,
    nazwa       TEXT NOT NULL,
    poziom      TEXT NOT NULL,
    kod_regionu TEXT REFERENCES dim_region(kod)
);

CREATE TABLE dim_wskaznik (
    wskaznik_id     SERIAL PRIMARY KEY,
    nazwa_wskaznika TEXT NOT NULL,
    jednostka_miary TEXT NOT NULL,
    grupa           TEXT,
    podgrupa        TEXT,
    poziom_nuts     TEXT
);

CREATE TABLE fakt_regionalne (
    kod         TEXT NOT NULL REFERENCES dim_region(kod),
    wskaznik_id INT  NOT NULL REFERENCES dim_wskaznik(wskaznik_id),
    rok         INT  NOT NULL,
    wartosc     NUMERIC,
    PRIMARY KEY (kod, wskaznik_id, rok)
);

CREATE TABLE fakt_wdb_sekcje (
    kod          TEXT NOT NULL REFERENCES dim_region(kod),
    rok          INT  NOT NULL,
    sekcja       TEXT NOT NULL,
    udzial_proc  NUMERIC,
    PRIMARY KEY (kod, rok, sekcja)
);
"""


#Klasa towrzaca proces etl pobiera wszystkie csv i wrzuca do postgresa postawionego na dockerze zanim
class Proces_Etl:
    def __init__(self):

        url = f"postgresql+psycopg2://{db_user}:{db_password}@localhost:{db_port}/{db_name}"
        self.engine = create_engine(url)

    def create_base(self):
        with self.engine.begin() as conn:
            conn.execute(text(sql))



    def extract1(self, path ='dane', sheet_name="DANE"):
        pliki_excel = glob.glob(os.path.join(path, '*.xlsx'))
        self.dataframes = {}
        for plik in pliki_excel:
            nazwa_pliku = os.path.basename(plik)
            self.dataframes[nazwa_pliku] = pd.read_excel(plik, sheet_name=sheet_name)


    #printuje informacje na temat danych pobranych
    def showing_info1(self, df: pd.DataFrame):
        print(self.dataframes.keys())
        print(df.head())
        print(f"{10*'-'}info{10*'-'}")
        print(df.shape)
        print(f"{10 * '-'}kolumny{10 * '-'}")
        print(df.columns)
        print(f"{10 * '-'}puste wartosci{10 * '-'}")
        print(df.isnull().sum())

    def show_info(self, number=0):
        if number == 0:
            ile = 0
            for key, df in self.dataframes.items():
                print(f"\n{10 * '==='} Tabsela: {key} {10 * '==='}")
                self.showing_info1(df)
                ile += 1
            print(f"Razem jest {ile} tabel")
        else:
            # Dopasowanie klucza do nazw plików Excel
            key = f"arkusz{number}.xlsx"
            if key in self.dataframes:
                df = self.dataframes[key]
                print(f"\n{10 * '==='} Tabela: {key} {10 * '==='}")
                self.showing_info1(df)
            else:
                print(f"Brak tabeli: {key}")

    #atrybuty najpierw pokazuja ktore wiersze sa nie sa uzupelnione a potem lekko useless
    def transform_1(self):



        for key, df in self.dataframes.items():
            df = df[(df['Atrybut'] != 'x') & (df['Atrybut'] != 'n')] #wywalenie pustych wierszy znalezionych przez tworzacego excela
            df.drop("Atrybut", axis=1, inplace=True)  #wywalenie zbednej juz kolumy
            df["Wartosc"] = pd.to_numeric(df["Wartosc"]) #wartosc jest jakims cudem stringiem idk how
            self.dataframes[key] = df


    """
    przy usuwaniu (przynajmniej dla poczatkowych danych co ostalem na poczatku bylo to 14 csv) 
    trzbea zauwazyc ze teroretycznie wartosci 3,14,15 i 7 moze byc terotetycznie 0 malo prawdopodobne ale moze byc ja sie na tym nie znam
    
    """
    #plik prosty to taki w ktorym nie ma wartosci unikalnych w kolumnie 3, nieporsty to np 7 excel
    def check_type_of_file(self):
        self.plik_typ = {}
        for key, df in self.dataframes.items():
            kategoria_col = df.columns[2]
            if df[kategoria_col].nunique() > 1:
                self.plik_typ[key] = "wielokategoryjny"
            else:
                self.plik_typ[key] = "prosty"

    def dim_regional(self):

        #iteruje po tabeli i szuka pierszy plik zawierajacy w kolumnie nazwa podregion tak bysmy wszystkie kraje, regiony i podregiony znalezc i dac to dim table
        plik_nuts3 = next(k for k, df in self.dataframes.items() if df["Nazwa"].str.startswith("PODREGION").any())



        df = self.dataframes[plik_nuts3]

        regiony = df[["Kod", "Nazwa"]].drop_duplicates().copy()# tylko to musmimy pobrac reszte jestejmy w stanie smai stworzyc
        regiony["kod"] = regiony["Kod"].astype(str)
        regiony["nazwa"] = regiony["Nazwa"]
        regiony["poziom"] = regiony["nazwa"].apply(self.poziom_z_nazwy) #Polska to polska, region to nuts2, podregion nuts3
        regiony["prefix4"] = regiony["kod"].str[:4]

        prefix_do_kodu = dict(zip(
            regiony.loc[regiony["poziom"] == "NUTS2", "prefix4"],
            regiony.loc[regiony["poziom"] == "NUTS2", "kod"],
        ))
        regiony["kod_regionu"] = regiony.apply(
            lambda r: prefix_do_kodu.get(r["prefix4"]) if r["poziom"] == "NUTS3" else None, axis=1
        )
        self.dim_region = regiony[["kod", "nazwa", "poziom", "kod_regionu"]]

    #jak Polska to polska region to nuts2 podregion to nuts3
    def poziom_z_nazwy(self, nazwa):
        if nazwa.startswith("POLSKA"):
            return "POLSKA"
        if nazwa.startswith("REGION"):
            return "NUTS2"
        return "NUTS3"





    #po to bysmy wiedzieli co mierzymy
    def dim_wskaznik_make(self):
        wiersze = []
        for key, typ in self.plik_typ.items():
            if typ != "prosty": #jak tam jest wiele kategorii damy temu osobne traktowanie
                continue
            df = self.dataframes[key]
            kategoria_col = df.columns[2] #to sie zmienia dla exceli
            wiersze.append({
                "plik": key,
                "nazwa_wskaznika": str(df[kategoria_col].iloc[0]), #pierwzy wiesz bo prosty to ma zawsze to samo
                "jednostka_miary": str(df["Jednostka miary"].iloc[0]),
                "poziom_nuts": "NUTS3" if df["Nazwa"].str.startswith("PODREGION").any() else "NUTS2",
            })
        self.wskazniki_meta = pd.DataFrame(wiersze)  # <- ta, z "plik", zostaje dla fakt_regionalne
        self.dim_wskaznik = self.wskazniki_meta.drop(columns="plik")
    #te normalne z jenda wartoscia w kolumnie 3
    def zbuduj_fakt_regionalne(self):
        df1 = []
        for _, meta in self.wskazniki_meta.iterrows():
            df2 = self.dataframes[meta["plik"]]
            df1.append(pd.DataFrame({
                "kod": df2["Kod"].astype(str),
                "nazwa_wskaznika": meta["nazwa_wskaznika"],
                "rok": df2["Rok"],
                "wartosc": df2["Wartosc"],
            }))
        self.fakt_regionalne = pd.concat(df1, ignore_index=True)




    #robimy skecje dla wielokategoryjnych osobna imo nie ma co tego mieszac moznaby teroretycznie zrobic porozbijac to ale to osobny pomysl mozna dorealizowac
    def zbuduj_fakt_wdb_sekcje(self):
        pliki = [k for k, t in self.plik_typ.items() if t == "wielokategoryjny"]
        df = []
        for key in pliki:
            df2 = self.dataframes[key]
            kategoria_col = df2.columns[2]
            df.append(pd.DataFrame({
                "kod": df2["Kod"].astype(str),
                "rok": df2["Rok"],
                "sekcja": df2[kategoria_col],
                "udzial_proc": df2["Wartosc"],
            }))
        self.fakt_wdb_sekcje = pd.concat(df, ignore_index=True)

    def reset_baza(self):
        with self.engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS fakt_wdb_sekcje"))
            conn.execute(text("DROP TABLE IF EXISTS fakt_regionalne"))
            conn.execute(text("DROP TABLE IF EXISTS dim_wskaznik"))
            conn.execute(text("DROP TABLE IF EXISTS dim_region"))




    #na razie reset zalozenie prjektowe ze bedziemy podmienaili csv dla nowych danych po prostu nie mialem lepszego pomyslu, z appendem najwyzej mozna sie pobawic z apsisanie porownaniem itp
    def load(self):
        self.reset_baza()
        self.create_base()
        nuts3 = self.dim_region["poziom"] == "NUTS3"
        #chcemy wpierw zapisac polske i nuts2 a dopiero potem nuts3 bo wiersz dziecko inaczej nie zadziala:/ najpierw rodzice a to sie odowluje do samego dsibie odregiony maja rozicow regionow
        self.dim_region[~nuts3].to_sql("dim_region", self.engine, if_exists="append", index=False)
        self.dim_region[nuts3].to_sql("dim_region", self.engine, if_exists="append", index=False)

        self.dim_wskaznik.to_sql("dim_wskaznik", self.engine, if_exists="append", index=False)

        ids = pd.read_sql("SELECT wskaznik_id, nazwa_wskaznika FROM dim_wskaznik", self.engine) #pobranie wygenerowanych wskaznikow
        nazwa_do_id = dict(zip(ids["nazwa_wskaznika"], ids["wskaznik_id"])) #tworzy dict
        self.fakt_regionalne["wskaznik_id"] = self.fakt_regionalne["nazwa_wskaznika"].map(nazwa_do_id) #przechodzimy przez kolumne nazwa wskaznika i przypisujemy odpowiednia wartosc na podstawie klucza
        self.fakt_regionalne.drop(columns="nazwa_wskaznika").to_sql("fakt_regionalne", self.engine, if_exists="append", index=False ) #usuwamy nieoitrzebna juz kolumne

        self.fakt_wdb_sekcje.to_sql("fakt_wdb_sekcje", self.engine, if_exists="append", index=False)

    #i wszystko zrobione
    def execute_all(self):
        self.extract1()
        self.transform_1()
        self.check_type_of_file()
        self.dim_regional()
        self.dim_wskaznik_make()
        self.zbuduj_fakt_regionalne()
        self.zbuduj_fakt_wdb_sekcje()
        self.load()  # load() sam woła reset_baza() + create_base() na początku
        print("Przeszlo")

    #TODO mozna potem dorobic czy aby na pewno nie ma pustych wierszy



