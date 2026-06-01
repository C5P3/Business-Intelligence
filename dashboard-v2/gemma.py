import os
import requests

OLLAMA_URL   = os.getenv("OLLAMA_URL",   "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma3:2b")


def is_available() -> bool:
    """Prüft ob Ollama läuft und das Modell geladen ist."""
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        if r.status_code != 200:
            return False
        models = [m["name"] for m in r.json().get("models", [])]
        return any(OLLAMA_MODEL.split(":")[0] in m for m in models)
    except Exception:
        return False


def generate_pricing_memo(
    route: str,
    avg_price: float,
    min_price: float,
    max_price: float,
    std_price: float,
    market_avg: float,
    load_factor: float,
    total_flights: int,
    bookings: int,
    airlines: list,
) -> str:
    price_diff_pct = (avg_price - market_avg) / market_avg * 100 if market_avg else 0
    airlines_str   = ", ".join(airlines) if airlines else "unbekannt"

    prompt = f"""Du bist ein erfahrener Airline Revenue-Manager.
Schreibe ein präzises Pricing-Memo auf Deutsch (max. 120 Wörter, keine Aufzählungen, Fliesstext).

ROUTENDATEN:
- Route: {route}
- Airlines: {airlines_str}
- Flüge gesamt: {total_flights:,}
- Buchungen: {bookings:,}
- Ø Preis: ${avg_price:.2f} ({price_diff_pct:+.1f}% vs. Markt ${market_avg:.2f})
- Preisrange: ${min_price:.2f} – ${max_price:.2f} (Std.abw. ${std_price:.2f})
- Load Factor: {load_factor:.1f}%

AUFGABE: Beantworte klar: Soll der Preis erhöht, gesenkt oder beibehalten werden?
Begründe mit den Daten. Schliesse mit einer konkreten Preisempfehlung ab ($-Betrag oder %-Änderung)."""

    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"temperature": 0.3, "num_predict": 200},
            },
            timeout=90,
        )
        if response.status_code == 200:
            return response.json()["message"]["content"]
        return f"Ollama-Fehler: HTTP {response.status_code} — {response.text[:200]}"
    except requests.exceptions.ConnectionError:
        return (
            "Ollama ist nicht erreichbar.\n\n"
            "Starte Ollama mit `ollama serve` und stelle sicher, "
            f"dass das Modell `{OLLAMA_MODEL}` geladen ist:\n"
            f"`ollama pull {OLLAMA_MODEL}`"
        )
    except requests.exceptions.Timeout:
        return "Timeout: Das Modell antwortet nicht (>90s). Versuche ein kleineres Modell."
    except Exception as e:
        return f"Unerwarteter Fehler: {e}"
