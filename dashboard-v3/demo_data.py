"""
Demo-Daten-Generator für Dashboard V3.

Wird genutzt, wenn keine MySQL-Verbindung besteht (z. B. zur Vorschau des UIs
oder für automatisierte Tests). Erzeugt plausible, aber rein synthetische Routen,
damit die Entscheidungslogik und die Charts ohne laufende Datenbank funktionieren.

WICHTIG: Diese Zahlen sind erfunden. Im Dashboard wird das durch ein deutliches
Banner kenntlich gemacht. Sobald die echte `flughafendb` erreichbar ist, werden
ausschliesslich echte Daten verwendet.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Ein paar Städte, um realistische Routennamen zu bauen.
_CITIES = [
    "Zürich", "Genf", "Basel", "Frankfurt", "München", "Berlin", "Wien",
    "Paris", "London", "Amsterdam", "Madrid", "Barcelona", "Rom", "Mailand",
    "Lissabon", "Kopenhagen", "Stockholm", "Oslo", "Helsinki", "Prag",
    "Warschau", "Budapest", "Athen", "Istanbul", "Dublin", "Brüssel",
    "New York", "Chicago", "Los Angeles", "Miami", "Boston", "Denver",
    "Toronto", "Dubai", "Singapur", "Tokio", "Hongkong", "Sydney",
]

_AIRLINES = [
    "Alpine Air", "Helvetia Wings", "EuroConnect", "NordJet", "SkyBridge",
    "Continental Star", "BlueHorizon", "MetroFly", "GlobalLink", "AeroSwiss",
]


def generate_scorecard(n_routes: int = 180, seed: int = 42) -> pd.DataFrame:
    """Erzeugt einen synthetischen Routen-Scorecard-DataFrame.

    Spalten entsprechen exakt dem, was queries.load_scorecard() aus der echten
    Datenbank liefert, damit das restliche Programm keinen Unterschied bemerkt.
    """
    rng = np.random.default_rng(seed)

    # Eindeutige Stadt-Paare ziehen.
    pairs: set[tuple[str, str]] = set()
    while len(pairs) < n_routes:
        a, b = rng.choice(len(_CITIES), size=2, replace=False)
        pairs.add((_CITIES[a], _CITIES[b]))
    pairs = list(pairs)

    rows = []
    for i, (von, nach) in enumerate(pairs):
        # Flugfrequenz log-normal verteilt: viele kleine, wenige grosse Routen.
        total_flights = int(np.clip(rng.lognormal(mean=4.2, sigma=1.1), 10, 2500))
        avg_cap = int(rng.integers(120, 260))
        total_capacity = total_flights * avg_cap

        # Load Factor: Beta-verteilt um ~0.62, ergibt realistische Streuung.
        load_factor = float(np.clip(rng.beta(5, 3) * 100, 8, 99))
        bookings = int(total_capacity * load_factor / 100)

        avg_price = float(np.clip(rng.normal(260, 90), 60, 720))
        std_price = float(avg_price * rng.uniform(0.12, 0.35))
        min_price = float(max(avg_price - std_price * rng.uniform(1.5, 2.5), 20))
        max_price = float(avg_price + std_price * rng.uniform(1.5, 3.0))
        revenue = float(bookings * avg_price * rng.uniform(0.9, 1.1))

        rows.append(
            {
                "route": f"{von} → {nach}",
                "von": 1000 + i,
                "nach": 5000 + i,
                "von_stadt": von,
                "nach_stadt": nach,
                "bookings": bookings,
                "revenue": round(revenue, 2),
                "avg_price": round(avg_price, 2),
                "min_price": round(min_price, 2),
                "max_price": round(max_price, 2),
                "std_price": round(std_price, 2),
                "total_flights": total_flights,
                "total_capacity": total_capacity,
                "load_factor": round(load_factor, 1),
            }
        )

    return pd.DataFrame(rows)


def generate_monthly(scorecard: pd.DataFrame, seed: int = 42) -> pd.DataFrame:
    """Erzeugt synthetische Monats-Zeitreihen (3 Monate) passend zum Scorecard.

    Liefert eine Zeile pro Route × Monat mit revenue/bookings – analog zur echten
    Query get_route_monthly().
    """
    rng = np.random.default_rng(seed + 1)
    months = ["2015-06", "2015-07", "2015-08"]
    out = []
    for _, r in scorecard.iterrows():
        # Trendfaktor pro Route: manche wachsen, manche schrumpfen.
        trend = rng.normal(0, 0.18)  # -18% .. +18% pro Monat im Mittel
        base = r["revenue"] / 3.0
        base_b = r["bookings"] / 3.0
        for k, m in enumerate(months):
            factor = (1 + trend) ** k * rng.uniform(0.9, 1.1)
            out.append(
                {
                    "von": r["von"],
                    "nach": r["nach"],
                    "month": m,
                    "revenue": round(max(base * factor, 0), 2),
                    "bookings": int(max(base_b * factor, 0)),
                }
            )
    return pd.DataFrame(out)


def generate_route_airlines(scorecard: pd.DataFrame, seed: int = 42) -> dict:
    """Ordnet jeder Route 1–3 fiktive Airlines zu (für das Routen-Cockpit)."""
    rng = np.random.default_rng(seed + 2)
    mapping = {}
    for _, r in scorecard.iterrows():
        k = int(rng.integers(1, 4))
        idx = rng.choice(len(_AIRLINES), size=k, replace=False)
        mapping[(r["von"], r["nach"])] = [_AIRLINES[j] for j in idx]
    return mapping
