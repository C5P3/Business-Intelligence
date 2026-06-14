"""
Entscheidungslogik für Dashboard V3 — Streich-Score & Impact-Simulation.

Diese Datei ist bewusst frei von Streamlit, SQL und LLM: reine Pandas-/NumPy-
Funktionen, die sich deterministisch testen lassen. Genau hier wird die
"Route streichen?"-Entscheidung berechnet — NICHT im LLM. Das LLM formuliert
später nur die Begründung (siehe llm.py).

Grundidee des Streich-Scores
----------------------------
Wir haben in dieser Datenbank KEINE Kostendaten, also lässt sich keine echte
Profitabilität berechnen. Der Streich-Score ist deshalb ein transparenter
*Schwäche-Index* aus fünf Signalen, jeweils 0..1 (1 = stärkstes Streich-Signal):

  * Auslastung (load_factor)      – niedrig  => Streich-Signal
  * Umsatz (revenue)              – niedrig  => Streich-Signal
  * Umsatz pro Flug (rev_per_flight) – niedrig => Streich-Signal
  * Buchungsvolumen (bookings)    – niedrig  => Streich-Signal
  * Trend (trend_pct)             – fallend  => Streich-Signal

Jedes Signal wird als Perzentil-Rang über alle Routen normalisiert (robust
gegen Ausreisser). Der gewichtete Mittelwert ergibt cut_score ∈ [0, 100].
Die Gewichte sind im Dashboard per Slider einstellbar — Entscheider sollen
die Logik nachvollziehen und anpassen können.
"""

from __future__ import annotations

import pandas as pd

# Empfehlungs-Labels (zentral, damit App & LLM denselben Wortlaut nutzen)
REC_CUT = "Streichen prüfen"
REC_WATCH = "Beobachten"
REC_KEEP = "Behalten"

# Standard-Gewichte (Summe = 1.0). Auslastung & Umsatz dominieren.
DEFAULT_WEIGHTS = {
    "load_factor": 0.30,
    "revenue": 0.25,
    "rev_per_flight": 0.20,
    "bookings": 0.15,
    "trend": 0.10,
}

# Sprechende Namen der Treiber (für Tabelle & LLM-Memo)
DRIVER_LABELS = {
    "load_factor": "schwache Auslastung",
    "revenue": "geringer Umsatz",
    "rev_per_flight": "niedriger Umsatz pro Flug",
    "bookings": "geringes Buchungsvolumen",
    "trend": "fallender Trend",
}


def _pct_rank(s: pd.Series) -> pd.Series:
    """Perzentil-Rang 0..1. Bei konstanter Spalte neutral 0.5."""
    if s.nunique(dropna=True) <= 1:
        return pd.Series(0.5, index=s.index)
    return s.rank(pct=True, method="average")


def normalize_weights(weights: dict | None) -> dict:
    """Stellt sicher, dass die Gewichte auf 1.0 summieren."""
    w = dict(DEFAULT_WEIGHTS if weights is None else weights)
    # Nur bekannte Keys behalten, fehlende mit 0 ergänzen.
    w = {k: float(w.get(k, 0.0)) for k in DEFAULT_WEIGHTS}
    total = sum(w.values())
    if total <= 0:
        return dict(DEFAULT_WEIGHTS)
    return {k: v / total for k, v in w.items()}


def compute_scores(df: pd.DataFrame, weights: dict | None = None) -> pd.DataFrame:
    """Berechnet Sub-Signale, cut_score (0..100) und den Haupttreiber je Route."""
    if df.empty:
        out = df.copy()
        for c in ["cut_lf", "cut_rev", "cut_rpf", "cut_vol", "cut_trend",
                  "cut_score", "main_driver"]:
            out[c] = [] if c == "main_driver" else pd.Series(dtype=float)
        return out

    w = normalize_weights(weights)
    out = df.copy()

    # Jedes Signal: hoher Wert = gut => "Schwäche" = 1 - Rang.
    out["cut_lf"] = 1.0 - _pct_rank(out["load_factor"])
    out["cut_rev"] = 1.0 - _pct_rank(out["revenue"])
    out["cut_rpf"] = 1.0 - _pct_rank(out["rev_per_flight"])
    out["cut_vol"] = 1.0 - _pct_rank(out["bookings"])
    out["cut_trend"] = 1.0 - _pct_rank(out["trend_pct"])

    # Gewichtete Beiträge -> Score 0..100
    contrib = pd.DataFrame({
        "load_factor": w["load_factor"] * out["cut_lf"],
        "revenue": w["revenue"] * out["cut_rev"],
        "rev_per_flight": w["rev_per_flight"] * out["cut_rpf"],
        "bookings": w["bookings"] * out["cut_vol"],
        "trend": w["trend"] * out["cut_trend"],
    }, index=out.index)

    out["cut_score"] = (contrib.sum(axis=1) * 100).round(1)
    # Haupttreiber = Signal mit dem grössten gewichteten Beitrag.
    out["main_driver"] = contrib.idxmax(axis=1).map(DRIVER_LABELS)
    return out


def classify(
    df: pd.DataFrame,
    cut_threshold: float = 65.0,
    watch_threshold: float = 45.0,
    protect_top_revenue_pct: float = 0.15,
    protect_load_factor: float = 85.0,
) -> pd.DataFrame:
    """Wandelt cut_score in eine Empfehlung um und schützt strategische Routen.

    Guardrails (Schutz vor Fehlentscheid):
      * Routen unter den umsatzstärksten `protect_top_revenue_pct` werden NICHT
        zum Streichen vorgeschlagen (max. "Beobachten") — hoher Absolutumsatz
        wiegt schwächere Effizienz auf.
      * Routen mit sehr hoher Auslastung (>= protect_load_factor) ebenso.
    """
    out = df.copy()
    if out.empty:
        out["recommendation"] = []
        out["protected"] = []
        return out

    def base(score):
        if score >= cut_threshold:
            return REC_CUT
        if score >= watch_threshold:
            return REC_WATCH
        return REC_KEEP

    out["recommendation"] = out["cut_score"].map(base)

    # Schutzschwelle für Umsatz (oberstes Quantil).
    if len(out) >= 5 and 0 < protect_top_revenue_pct < 1:
        rev_cut = out["revenue"].quantile(1 - protect_top_revenue_pct)
    else:
        rev_cut = float("inf")

    protected = (out["revenue"] >= rev_cut) | (out["load_factor"] >= protect_load_factor)
    out["protected"] = protected

    # Schutz: nie "Streichen prüfen", sondern höchstens "Beobachten".
    mask = protected & (out["recommendation"] == REC_CUT)
    out.loc[mask, "recommendation"] = REC_WATCH
    return out


def analyze(
    df: pd.DataFrame,
    weights: dict | None = None,
    cut_threshold: float = 65.0,
    watch_threshold: float = 45.0,
    protect_top_revenue_pct: float = 0.15,
    protect_load_factor: float = 85.0,
) -> pd.DataFrame:
    """Komplettpipeline: Scores berechnen + klassifizieren."""
    scored = compute_scores(df, weights)
    return classify(
        scored,
        cut_threshold=cut_threshold,
        watch_threshold=watch_threshold,
        protect_top_revenue_pct=protect_top_revenue_pct,
        protect_load_factor=protect_load_factor,
    )


def simulate_cut(
    scorecard: pd.DataFrame,
    cut_mask: pd.Series,
    rebooking_rate: float = 0.0,
) -> dict:
    """Simuliert die Auswirkung, eine Auswahl von Routen zu streichen.

    rebooking_rate ∈ [0,1]: Anteil der Buchungen, der auf anderen Routen
    erneut bucht (und damit Umsatz rettet). 0 = konservativ (alles verloren).
    """
    total_rev = float(scorecard["revenue"].sum())
    total_fl = int(scorecard["total_flights"].sum())
    total_seats = float(scorecard["total_capacity"].sum())
    total_bk = int(scorecard["bookings"].sum())

    cut = scorecard[cut_mask]
    rev_gross = float(cut["revenue"].sum())
    rebooking_rate = min(max(rebooking_rate, 0.0), 1.0)
    rev_recovered = rev_gross * rebooking_rate
    rev_net = rev_gross - rev_recovered

    flights_freed = int(cut["total_flights"].sum())
    seats_freed = float(cut["total_capacity"].sum())
    bookings_affected = int(cut["bookings"].sum())

    return {
        "n_routes_cut": int(len(cut)),
        "revenue_lost_gross": round(rev_gross, 2),
        "revenue_recovered": round(rev_recovered, 2),
        "revenue_lost_net": round(rev_net, 2),
        "pct_of_network_revenue": round(rev_gross / total_rev * 100, 2) if total_rev else 0.0,
        "flights_freed": flights_freed,
        "pct_of_flights": round(flights_freed / total_fl * 100, 2) if total_fl else 0.0,
        "seats_freed": round(seats_freed, 0),
        "bookings_affected": bookings_affected,
        "pct_of_bookings": round(bookings_affected / total_bk * 100, 2) if total_bk else 0.0,
        "rebooking_rate": rebooking_rate,
    }


def route_facts(row: pd.Series, network: dict) -> dict:
    """Bündelt die Kennzahlen einer Route als JSON-fähiges Dict — Eingabe fürs LLM."""
    rev = float(row["revenue"])
    net_rev = network.get("total_revenue", 0) or 0
    return {
        "route": row["route"],
        "recommendation": row.get("recommendation"),
        "cut_score": float(row.get("cut_score", 0)),
        "main_driver": row.get("main_driver"),
        "protected": bool(row.get("protected", False)),
        "load_factor": float(row["load_factor"]),
        "avg_price": float(row["avg_price"]),
        "revenue": rev,
        "revenue_share_pct": round(rev / net_rev * 100, 3) if net_rev else 0.0,
        "bookings": int(row["bookings"]),
        "total_flights": int(row["total_flights"]),
        "rev_per_flight": float(row.get("rev_per_flight", 0)),
        "rev_per_seat": float(row.get("rev_per_seat", 0)),
        "trend_pct": float(row.get("trend_pct", 0)),
        "network_avg_ticket": network.get("avg_ticket", 0),
        "network_load_factor": network.get("network_load_factor", 0),
    }
