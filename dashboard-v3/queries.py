"""
Datenschicht für Dashboard V3 — Route Decision Cockpit.

Aufgaben:
  * Verbindung zur lokalen MySQL `flughafendb` (gleiche Konfiguration wie V1/V2).
  * Aggregation auf Routenebene (von → nach) inkl. Umsatz, Auslastung, Frequenz.
  * Monats-Zeitreihen je Route für die Trend-Berechnung.
  * Automatischer Fallback auf synthetische Demo-Daten, wenn keine DB erreichbar
    ist — so startet das Dashboard immer und lässt sich ohne Datenbank testen.

Designprinzip: Hier werden NUR Zahlen geliefert. Sämtliche Entscheidungslogik
(Scoring, Klassifikation) liegt in scoring.py, die Textgenerierung in llm.py.
"""

from __future__ import annotations

import os
import pandas as pd

import demo_data

# ── Streamlit-Cache-Shim ──────────────────────────────────────────────────────
# Damit queries.py auch ohne laufendes Streamlit importierbar/testbar bleibt.
try:
    import streamlit as st

    cache_data = st.cache_data
except Exception:  # pragma: no cover - nur ausserhalb von Streamlit
    def cache_data(*dargs, **dkwargs):
        def deco(fn):
            return fn

        # Erlaubt sowohl @cache_data als auch @cache_data(ttl=...)
        if len(dargs) == 1 and callable(dargs[0]) and not dkwargs:
            return dargs[0]
        return deco


DB_CONFIG = {
    "host": os.getenv("DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("DB_PORT", 3306)),
    "user": os.getenv("DB_USER", "flughafen-user"),
    "password": os.getenv("DB_PASSWORD", "secret"),
    "database": os.getenv("DB_NAME", "flughafendb"),
}

# Erzwingt Demo-Daten, auch wenn eine DB läuft (z. B. für Screenshots):
FORCE_DEMO = os.getenv("DASHBOARD_DEMO", "0") == "1"


# ── DB-Helfer ─────────────────────────────────────────────────────────────────

def _connect():
    import mysql.connector

    return mysql.connector.connect(connection_timeout=4, **DB_CONFIG)


def db_available() -> bool:
    """True, wenn eine echte DB-Verbindung möglich ist (und Demo nicht erzwungen)."""
    if FORCE_DEMO:
        return False
    try:
        conn = _connect()
        conn.close()
        return True
    except Exception:
        return False


def _query(sql: str) -> pd.DataFrame:
    conn = _connect()
    try:
        return pd.read_sql(sql, conn)
    finally:
        conn.close()


# ── SQL: Routen-Scorecard ─────────────────────────────────────────────────────
# Startet bei den FLÜGEN (rc) und hängt die Buchungen per LEFT JOIN an, damit
# auch schwach gebuchte Routen erscheinen — genau die sind Streich-Kandidaten.
# Kapazität wird einmal pro Flug summiert (nicht pro Buchung).

def _scorecard_sql(min_flights: int, limit: int) -> str:
    return f"""
        SELECT CONCAT(g1.stadt, ' → ', g2.stadt)                         AS route,
               rc.von, rc.nach,
               g1.stadt                                                  AS von_stadt,
               g2.stadt                                                  AS nach_stadt,
               COALESCE(rb.bookings, 0)                                  AS bookings,
               ROUND(COALESCE(rb.revenue, 0), 2)                         AS revenue,
               ROUND(COALESCE(rb.avg_price, 0), 2)                       AS avg_price,
               ROUND(COALESCE(rb.min_price, 0), 2)                       AS min_price,
               ROUND(COALESCE(rb.max_price, 0), 2)                       AS max_price,
               ROUND(COALESCE(rb.std_price, 0), 2)                       AS std_price,
               rc.total_flights,
               rc.total_capacity,
               ROUND(COALESCE(rb.bookings, 0)
                     / NULLIF(rc.total_capacity, 0) * 100, 1)            AS load_factor
        FROM (
            SELECT f.von, f.nach,
                   SUM(fz.kapazitaet) AS total_capacity,
                   COUNT(f.flug_id)   AS total_flights
            FROM flug f
            JOIN flugzeug fz ON f.flugzeug_id = fz.flugzeug_id
            GROUP BY f.von, f.nach
            HAVING COUNT(f.flug_id) >= {int(min_flights)}
        ) rc
        LEFT JOIN (
            SELECT f.von, f.nach,
                   COUNT(b.buchung_id) AS bookings,
                   SUM(b.preis)        AS revenue,
                   AVG(b.preis)        AS avg_price,
                   MIN(b.preis)        AS min_price,
                   MAX(b.preis)        AS max_price,
                   STDDEV(b.preis)     AS std_price
            FROM buchung b
            JOIN flug f ON b.flug_id = f.flug_id
            GROUP BY f.von, f.nach
        ) rb ON rc.von = rb.von AND rc.nach = rb.nach
        JOIN flughafen_geo g1 ON rc.von  = g1.flughafen_id
        JOIN flughafen_geo g2 ON rc.nach = g2.flughafen_id
        WHERE g1.stadt IS NOT NULL AND g2.stadt IS NOT NULL
        ORDER BY rc.total_flights DESC
        LIMIT {int(limit)}
    """


def _monthly_sql() -> str:
    return """
        SELECT f.von, f.nach,
               DATE_FORMAT(f.abflug, '%Y-%m') AS month,
               SUM(b.preis)        AS revenue,
               COUNT(b.buchung_id) AS bookings
        FROM buchung b
        JOIN flug f ON b.flug_id = f.flug_id
        GROUP BY f.von, f.nach, month
    """


def _airlines_sql(von: int, nach: int) -> str:
    return f"""
        SELECT DISTINCT fl.firmenname AS airline
        FROM flug f
        JOIN fluglinie fl ON f.fluglinie_id = fl.fluglinie_id
        WHERE f.von = {int(von)} AND f.nach = {int(nach)}
        LIMIT 6
    """


# ── Trend-Anreicherung (reine Pandas-Logik, ohne DB) ──────────────────────────

def add_trend(scorecard: pd.DataFrame, monthly: pd.DataFrame) -> pd.DataFrame:
    """Hängt eine Spalte `trend_pct` an: prozentuale Umsatzänderung erster→letzter
    Monat je Route. Positiv = wachsend, negativ = schrumpfend."""
    sc = scorecard.copy()
    if monthly is None or monthly.empty:
        sc["trend_pct"] = 0.0
        return sc

    trends = {}
    for (von, nach), grp in monthly.groupby(["von", "nach"]):
        grp = grp.sort_values("month")
        rev = grp["revenue"].tolist()
        if len(rev) >= 2 and rev[0] > 0:
            trends[(von, nach)] = (rev[-1] - rev[0]) / rev[0] * 100.0
        else:
            trends[(von, nach)] = 0.0

    sc["trend_pct"] = [
        round(trends.get((r.von, r.nach), 0.0), 1) for r in sc.itertuples()
    ]
    return sc


def add_efficiency(scorecard: pd.DataFrame) -> pd.DataFrame:
    """Umsatz pro Flug und pro Sitzplatz — robuste Effizienz-Kennzahlen."""
    sc = scorecard.copy()
    sc["rev_per_flight"] = (sc["revenue"] / sc["total_flights"].replace(0, pd.NA)).fillna(0).round(2)
    sc["rev_per_seat"] = (sc["revenue"] / sc["total_capacity"].replace(0, pd.NA)).fillna(0).round(2)
    return sc


# ── Öffentliche Hauptfunktion ─────────────────────────────────────────────────

@cache_data(ttl=600)
def get_dataset(min_flights: int = 20, limit: int = 800) -> dict:
    """Lädt den kompletten Datensatz für das Dashboard.

    Returns dict:
        scorecard : DataFrame (eine Zeile je Route, inkl. trend_pct & Effizienz)
        monthly   : DataFrame (Route × Monat)
        source    : "db" | "demo"
    """
    if db_available():
        try:
            sc = _query(_scorecard_sql(min_flights, limit))
            mon = _query(_monthly_sql())
            source = "db"
        except Exception:
            sc, mon, source = _demo_dataset(min_flights)
    else:
        sc, mon, source = _demo_dataset(min_flights)

    sc = add_efficiency(sc)
    sc = add_trend(sc, mon)
    # Stabile, sprechende Sortierung als Default.
    sc = sc.sort_values("revenue", ascending=False).reset_index(drop=True)
    return {"scorecard": sc, "monthly": mon, "source": source}


def _demo_dataset(min_flights: int):
    sc = demo_data.generate_scorecard()
    sc = sc[sc["total_flights"] >= min_flights].reset_index(drop=True)
    mon = demo_data.generate_monthly(sc)
    return sc, mon, "demo"


# ── Routen-Detailhelfer (für das Cockpit) ─────────────────────────────────────

def route_airlines(dataset: dict, von: int, nach: int) -> list[str]:
    """Airlines auf einer Route — DB-Query oder Demo-Mapping je nach Quelle."""
    if dataset.get("source") == "db":
        try:
            df = _query(_airlines_sql(von, nach))
            return df["airline"].tolist()
        except Exception:
            return []
    mapping = getattr(_demo_dataset, "_airlines_cache", None)
    if mapping is None:
        mapping = demo_data.generate_route_airlines(dataset["scorecard"])
        _demo_dataset._airlines_cache = mapping
    return mapping.get((von, nach), [])


def route_monthly(dataset: dict, von: int, nach: int) -> pd.DataFrame:
    """Monats-Zeitreihe einer einzelnen Route."""
    mon = dataset["monthly"]
    sub = mon[(mon["von"] == von) & (mon["nach"] == nach)].sort_values("month")
    return sub.reset_index(drop=True)


# ── Netzwerk-KPIs (aus dem Scorecard berechnet, keine Extra-Query) ────────────

def network_kpis(scorecard: pd.DataFrame) -> dict:
    total_rev = float(scorecard["revenue"].sum())
    total_bk = int(scorecard["bookings"].sum())
    total_fl = int(scorecard["total_flights"].sum())
    total_cap = float(scorecard["total_capacity"].sum())
    return {
        "total_revenue": total_rev,
        "total_bookings": total_bk,
        "total_flights": total_fl,
        "n_routes": int(len(scorecard)),
        "avg_ticket": round(total_rev / total_bk, 2) if total_bk else 0.0,
        "network_load_factor": round(total_bk / total_cap * 100, 1) if total_cap else 0.0,
    }
