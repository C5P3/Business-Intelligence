import os
import pandas as pd
import mysql.connector
import streamlit as st

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("DB_PORT", 3306)),
    "user": os.getenv("DB_USER", "flughafen-user"),
    "password": os.getenv("DB_PASSWORD", "secret"),
    "database": os.getenv("DB_NAME", "flughafendb"),
}

# MySQL gibt Wochentage auf Englisch zurück; Reihenfolge Mo–So
WEEKDAY_ORDER = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]


@st.cache_data(ttl=600)
def _query(sql: str) -> pd.DataFrame:
    conn = mysql.connector.connect(**DB_CONFIG)
    try:
        return pd.read_sql(sql, conn)
    finally:
        conn.close()


# ── Buchungs- & Umsatzanalyse ─────────────────────────────────────────────────

def get_kpis_bookings() -> dict:
    df = _query("""
        SELECT
            SUM(preis)                    AS total_revenue,
            COUNT(buchung_id)             AS total_bookings,
            AVG(preis)                    AS avg_price,
            COUNT(DISTINCT passagier_id)  AS passengers
        FROM buchung
    """)
    return df.iloc[0].to_dict()


def get_revenue_by_airline() -> pd.DataFrame:
    return _query("""
        SELECT fl.firmenname                   AS airlinename,
               SUM(b.preis)                   AS total_revenue,
               COUNT(b.buchung_id)            AS bookings
        FROM buchung    b
        JOIN flug       f  ON b.flug_id       = f.flug_id
        JOIN fluglinie  fl ON f.fluglinie_id  = fl.fluglinie_id
        GROUP BY fl.fluglinie_id, fl.firmenname
        ORDER BY total_revenue DESC
        LIMIT 15
    """)


def get_monthly_revenue() -> pd.DataFrame:
    return _query("""
        SELECT DATE_FORMAT(f.abflug, '%Y-%m') AS month,
               SUM(b.preis)                   AS revenue,
               COUNT(b.buchung_id)            AS bookings
        FROM buchung b
        JOIN flug    f ON b.flug_id = f.flug_id
        GROUP BY month
        ORDER BY month
    """)


def get_top_routes_revenue() -> pd.DataFrame:
    return _query("""
        SELECT CONCAT(g1.stadt, ' → ', g2.stadt) AS route,
               COUNT(b.buchung_id)               AS bookings,
               SUM(b.preis)                      AS revenue
        FROM buchung         b
        JOIN flug            f  ON b.flug_id        = f.flug_id
        JOIN flughafen_geo   g1 ON f.von            = g1.flughafen_id
        JOIN flughafen_geo   g2 ON f.nach           = g2.flughafen_id
        WHERE g1.stadt IS NOT NULL AND g2.stadt IS NOT NULL
        GROUP BY f.von, f.nach, g1.stadt, g2.stadt
        ORDER BY revenue DESC
        LIMIT 10
    """)


def get_load_factor() -> pd.DataFrame:
    return _query("""
        SELECT fl.firmenname                                                            AS airlinename,
               COUNT(b.buchung_id)                                                     AS total_bookings,
               SUM(fz.kapazitaet)                                                      AS total_capacity,
               ROUND(COUNT(b.buchung_id) / NULLIF(SUM(fz.kapazitaet), 0) * 100, 1)   AS load_factor
        FROM buchung    b
        JOIN flug       f  ON b.flug_id      = f.flug_id
        JOIN fluglinie  fl ON f.fluglinie_id = fl.fluglinie_id
        JOIN flugzeug   fz ON f.flugzeug_id  = fz.flugzeug_id
        GROUP BY fl.fluglinie_id, fl.firmenname
        ORDER BY load_factor DESC
        LIMIT 15
    """)


# ── Flugbetrieb & Routen ──────────────────────────────────────────────────────

def get_kpis_flights() -> dict:
    df = _query("""
        SELECT
            (SELECT COUNT(*) FROM flug)          AS total_flights,
            (SELECT COUNT(*) FROM fluglinie)     AS airlines,
            (SELECT COUNT(*) FROM flughafen)     AS airports,
            (SELECT COUNT(*) FROM flugzeug_typ)  AS airplane_types
    """)
    return df.iloc[0].to_dict()


def get_top_routes_flights() -> pd.DataFrame:
    return _query("""
        SELECT CONCAT(g1.stadt, ' → ', g2.stadt) AS route,
               COUNT(f.flug_id)                  AS flights
        FROM flug           f
        JOIN flughafen_geo  g1 ON f.von  = g1.flughafen_id
        JOIN flughafen_geo  g2 ON f.nach = g2.flughafen_id
        WHERE g1.stadt IS NOT NULL AND g2.stadt IS NOT NULL
        GROUP BY f.von, f.nach, g1.stadt, g2.stadt
        ORDER BY flights DESC
        LIMIT 10
    """)


def get_flights_per_airline() -> pd.DataFrame:
    return _query("""
        SELECT fl.firmenname        AS airlinename,
               COUNT(f.flug_id)    AS flights
        FROM flug       f
        JOIN fluglinie  fl ON f.fluglinie_id = fl.fluglinie_id
        GROUP BY fl.fluglinie_id, fl.firmenname
        ORDER BY flights DESC
        LIMIT 15
    """)


def get_flights_per_weekday() -> pd.DataFrame:
    df = _query("""
        SELECT DAYNAME(abflug)    AS weekday,
               DAYOFWEEK(abflug) AS day_num,
               COUNT(*)          AS flights
        FROM flug
        GROUP BY weekday, day_num
        ORDER BY day_num
    """)
    df["weekday"] = pd.Categorical(df["weekday"], categories=WEEKDAY_ORDER, ordered=True)
    return df.sort_values("weekday")


def get_top_departure_airports() -> pd.DataFrame:
    return _query("""
        SELECT g.stadt              AS city,
               g.land               AS country,
               COUNT(f.flug_id)    AS departures
        FROM flug           f
        JOIN flughafen_geo  g ON f.von = g.flughafen_id
        WHERE g.stadt IS NOT NULL
        GROUP BY f.von, g.stadt, g.land
        ORDER BY departures DESC
        LIMIT 10
    """)


def get_monthly_flights() -> pd.DataFrame:
    return _query("""
        SELECT DATE_FORMAT(abflug, '%Y-%m') AS month,
               COUNT(*)                     AS flights
        FROM flug
        GROUP BY month
        ORDER BY month
    """)
