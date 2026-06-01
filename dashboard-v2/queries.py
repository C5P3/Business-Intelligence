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

WEEKDAY_ORDER = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]


@st.cache_data(ttl=600)
def _query(sql: str) -> pd.DataFrame:
    conn = mysql.connector.connect(**DB_CONFIG)
    try:
        return pd.read_sql(sql, conn)
    finally:
        conn.close()


# ── Marktüberblick ────────────────────────────────────────────────────────────

def get_kpis() -> dict:
    df = _query("""
        SELECT
            ROUND(AVG(preis), 2)    AS avg_price,
            ROUND(MIN(preis), 2)    AS min_price,
            ROUND(MAX(preis), 2)    AS max_price,
            ROUND(STDDEV(preis), 2) AS std_price,
            COUNT(*)                AS total_bookings
        FROM buchung
    """)
    return df.iloc[0].to_dict()


def get_price_distribution() -> pd.DataFrame:
    return _query("""
        SELECT
            CASE
                WHEN preis <  100 THEN '< $100'
                WHEN preis <  200 THEN '$100–200'
                WHEN preis <  300 THEN '$200–300'
                WHEN preis <  400 THEN '$300–400'
                WHEN preis <  500 THEN '$400–500'
                ELSE                   '> $500'
            END AS bucket,
            CASE
                WHEN preis <  100 THEN 1
                WHEN preis <  200 THEN 2
                WHEN preis <  300 THEN 3
                WHEN preis <  400 THEN 4
                WHEN preis <  500 THEN 5
                ELSE                   6
            END AS sort_order,
            COUNT(*) AS bookings
        FROM buchung
        GROUP BY bucket, sort_order
        ORDER BY sort_order
    """)


def get_weekday_prices() -> pd.DataFrame:
    df = _query("""
        SELECT DAYNAME(f.abflug)    AS weekday,
               DAYOFWEEK(f.abflug) AS day_num,
               ROUND(AVG(b.preis), 2) AS avg_price,
               COUNT(b.buchung_id)    AS bookings
        FROM buchung b
        JOIN flug f ON b.flug_id = f.flug_id
        GROUP BY weekday, day_num
        ORDER BY day_num
    """)
    df["weekday"] = pd.Categorical(df["weekday"], categories=WEEKDAY_ORDER, ordered=True)
    return df.sort_values("weekday")


def get_monthly_prices() -> pd.DataFrame:
    return _query("""
        SELECT DATE_FORMAT(f.abflug, '%Y-%m') AS month,
               ROUND(AVG(b.preis), 2)         AS avg_price,
               COUNT(b.buchung_id)             AS bookings
        FROM buchung b
        JOIN flug f ON b.flug_id = f.flug_id
        GROUP BY month
        ORDER BY month
    """)


# ── Entscheidungsmatrix ───────────────────────────────────────────────────────

def get_price_load_matrix() -> pd.DataFrame:
    """
    Aggregiert auf Routenebene: Durchschnittspreis + korrekter Load Factor.
    Kapazität wird einmal pro Flug gezählt (Subquery), nicht pro Buchung.
    """
    return _query("""
        SELECT CONCAT(g1.stadt, ' → ', g2.stadt) AS route,
               rb.von_id,
               rb.nach_id,
               rb.bookings,
               ROUND(rb.avg_price, 2)                                        AS avg_price,
               ROUND(rb.min_price, 2)                                        AS min_price,
               ROUND(rb.max_price, 2)                                        AS max_price,
               rc.total_flights,
               ROUND(rb.bookings / NULLIF(rc.total_capacity, 0) * 100, 1)   AS load_factor
        FROM (
            SELECT f.von AS von_id, f.nach AS nach_id,
                   COUNT(b.buchung_id) AS bookings,
                   AVG(b.preis)        AS avg_price,
                   MIN(b.preis)        AS min_price,
                   MAX(b.preis)        AS max_price
            FROM buchung b
            JOIN flug f ON b.flug_id = f.flug_id
            GROUP BY f.von, f.nach
            HAVING COUNT(*) >= 200
        ) rb
        JOIN (
            SELECT f.von, f.nach,
                   SUM(fz.kapazitaet) AS total_capacity,
                   COUNT(f.flug_id)   AS total_flights
            FROM flug f
            JOIN flugzeug fz ON f.flugzeug_id = fz.flugzeug_id
            GROUP BY f.von, f.nach
        ) rc ON rb.von_id = rc.von AND rb.nach_id = rc.nach
        JOIN flughafen_geo g1 ON rb.von_id  = g1.flughafen_id
        JOIN flughafen_geo g2 ON rb.nach_id = g2.flughafen_id
        WHERE g1.stadt IS NOT NULL AND g2.stadt IS NOT NULL
        ORDER BY rb.bookings DESC
        LIMIT 300
    """)


# ── Route Benchmarking ────────────────────────────────────────────────────────

def get_overpriced_routes() -> pd.DataFrame:
    """Teuerste Routen mit unterdurchschnittlichem Load Factor → Preis senken."""
    return _query("""
        SELECT CONCAT(g1.stadt, ' → ', g2.stadt) AS route,
               ROUND(rb.avg_price, 2)                                       AS avg_price,
               rb.bookings,
               ROUND(rb.bookings / NULLIF(rc.total_capacity, 0) * 100, 1)  AS load_factor
        FROM (
            SELECT f.von AS von_id, f.nach AS nach_id,
                   COUNT(b.buchung_id) AS bookings,
                   AVG(b.preis)        AS avg_price
            FROM buchung b JOIN flug f ON b.flug_id = f.flug_id
            GROUP BY f.von, f.nach HAVING COUNT(*) >= 200
        ) rb
        JOIN (
            SELECT f.von, f.nach, SUM(fz.kapazitaet) AS total_capacity
            FROM flug f JOIN flugzeug fz ON f.flugzeug_id = fz.flugzeug_id
            GROUP BY f.von, f.nach
        ) rc ON rb.von_id = rc.von AND rb.nach_id = rc.nach
        JOIN flughafen_geo g1 ON rb.von_id  = g1.flughafen_id
        JOIN flughafen_geo g2 ON rb.nach_id = g2.flughafen_id
        WHERE g1.stadt IS NOT NULL AND g2.stadt IS NOT NULL
          AND rb.avg_price > (SELECT AVG(preis) FROM buchung)
          AND rb.bookings / NULLIF(rc.total_capacity, 0) < (
                SELECT AVG(b2.buchung_id / NULLIF(rc2.cap, 0))
                FROM (SELECT COUNT(*) AS buchung_id, f2.von, f2.nach FROM buchung b2 JOIN flug f2 ON b2.flug_id=f2.flug_id GROUP BY f2.von, f2.nach) b2
                JOIN (SELECT f3.von, f3.nach, SUM(fz2.kapazitaet) AS cap FROM flug f3 JOIN flugzeug fz2 ON f3.flugzeug_id=fz2.flugzeug_id GROUP BY f3.von, f3.nach) rc2
                ON b2.von = rc2.von AND b2.nach = rc2.nach
              )
        ORDER BY rb.avg_price DESC
        LIMIT 15
    """)


def get_underpriced_routes() -> pd.DataFrame:
    """Günstigste Routen mit überdurchschnittlichem Load Factor → Preis erhöhen."""
    return _query("""
        SELECT CONCAT(g1.stadt, ' → ', g2.stadt) AS route,
               ROUND(rb.avg_price, 2)                                       AS avg_price,
               rb.bookings,
               ROUND(rb.bookings / NULLIF(rc.total_capacity, 0) * 100, 1)  AS load_factor
        FROM (
            SELECT f.von AS von_id, f.nach AS nach_id,
                   COUNT(b.buchung_id) AS bookings,
                   AVG(b.preis)        AS avg_price
            FROM buchung b JOIN flug f ON b.flug_id = f.flug_id
            GROUP BY f.von, f.nach HAVING COUNT(*) >= 200
        ) rb
        JOIN (
            SELECT f.von, f.nach, SUM(fz.kapazitaet) AS total_capacity
            FROM flug f JOIN flugzeug fz ON f.flugzeug_id = fz.flugzeug_id
            GROUP BY f.von, f.nach
        ) rc ON rb.von_id = rc.von AND rb.nach_id = rc.nach
        JOIN flughafen_geo g1 ON rb.von_id  = g1.flughafen_id
        JOIN flughafen_geo g2 ON rb.nach_id = g2.flughafen_id
        WHERE g1.stadt IS NOT NULL AND g2.stadt IS NOT NULL
          AND rb.avg_price < (SELECT AVG(preis) FROM buchung)
        ORDER BY load_factor DESC
        LIMIT 15
    """)


def get_price_outliers() -> pd.DataFrame:
    """Buchungen mit Z-Score > 1.8 (starke Preisabweichung vom Routendurchschnitt)."""
    return _query("""
        SELECT CONCAT(g1.stadt, ' → ', g2.stadt) AS route,
               fl.firmenname                      AS airline,
               ROUND(b.preis, 2)                  AS price,
               ROUND(ra.avg_price, 2)             AS route_avg,
               ROUND((b.preis - ra.avg_price) / ra.std_price, 2) AS z_score,
               CASE WHEN b.preis > ra.avg_price THEN 'zu teuer' ELSE 'zu günstig' END AS typ
        FROM buchung b
        JOIN flug      f  ON b.flug_id       = f.flug_id
        JOIN fluglinie fl ON f.fluglinie_id  = fl.fluglinie_id
        JOIN flughafen_geo g1 ON f.von  = g1.flughafen_id
        JOIN flughafen_geo g2 ON f.nach = g2.flughafen_id
        JOIN (
            SELECT f2.von, f2.nach,
                   AVG(b2.preis)    AS avg_price,
                   STDDEV(b2.preis) AS std_price
            FROM buchung b2
            JOIN flug f2 ON b2.flug_id = f2.flug_id
            GROUP BY f2.von, f2.nach
            HAVING COUNT(*) >= 100 AND STDDEV(b2.preis) > 10
        ) ra ON f.von = ra.von AND f.nach = ra.nach
        WHERE g1.stadt IS NOT NULL AND g2.stadt IS NOT NULL
          AND ABS((b.preis - ra.avg_price) / ra.std_price) > 1.8
        ORDER BY ABS((b.preis - ra.avg_price) / ra.std_price) DESC
        LIMIT 30
    """)


# ── KI-Memo: Routendetail ─────────────────────────────────────────────────────

def get_route_selector() -> pd.DataFrame:
    """Top-Routen für den Dropdown-Selektor im KI-Memo."""
    return _query("""
        SELECT CONCAT(g1.stadt, ' → ', g2.stadt) AS route,
               f.von AS von_id, f.nach AS nach_id,
               COUNT(b.buchung_id)    AS bookings,
               ROUND(AVG(b.preis), 2) AS avg_price
        FROM buchung b
        JOIN flug f ON b.flug_id = f.flug_id
        JOIN flughafen_geo g1 ON f.von  = g1.flughafen_id
        JOIN flughafen_geo g2 ON f.nach = g2.flughafen_id
        WHERE g1.stadt IS NOT NULL AND g2.stadt IS NOT NULL
        GROUP BY f.von, f.nach, g1.stadt, g2.stadt
        HAVING COUNT(*) >= 200
        ORDER BY bookings DESC
        LIMIT 100
    """)


@st.cache_data(ttl=600)
def get_route_detail(von_id: int, nach_id: int) -> dict:
    """Vollständige Preis- und Kapazitätsdetails einer Route für das KI-Memo."""
    df_price = _query(f"""
        SELECT COUNT(b.buchung_id)    AS bookings,
               ROUND(AVG(b.preis),2)  AS avg_price,
               ROUND(MIN(b.preis),2)  AS min_price,
               ROUND(MAX(b.preis),2)  AS max_price,
               ROUND(STDDEV(b.preis),2) AS std_price
        FROM buchung b
        JOIN flug f ON b.flug_id = f.flug_id
        WHERE f.von = {von_id} AND f.nach = {nach_id}
    """)
    df_cap = _query(f"""
        SELECT SUM(fz.kapazitaet) AS total_capacity,
               COUNT(f.flug_id)   AS total_flights
        FROM flug f JOIN flugzeug fz ON f.flugzeug_id = fz.flugzeug_id
        WHERE f.von = {von_id} AND f.nach = {nach_id}
    """)
    df_airlines = _query(f"""
        SELECT DISTINCT fl.firmenname AS airline
        FROM flug f JOIN fluglinie fl ON f.fluglinie_id = fl.fluglinie_id
        WHERE f.von = {von_id} AND f.nach = {nach_id}
        LIMIT 5
    """)
    df_market = _query("SELECT ROUND(AVG(preis),2) AS market_avg FROM buchung")

    row = df_price.iloc[0].to_dict()
    cap = df_cap.iloc[0].to_dict()
    row["total_capacity"] = cap["total_capacity"]
    row["total_flights"]  = cap["total_flights"]
    row["load_factor"]    = round(
        row["bookings"] / cap["total_capacity"] * 100, 1
    ) if cap["total_capacity"] else 0
    row["market_avg"]   = df_market.iloc[0]["market_avg"]
    row["airlines"]     = df_airlines["airline"].tolist()
    return row
