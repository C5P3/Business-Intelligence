"""
Lokale LLM-Anbindung für Dashboard V3 (Ollama).

Architektur-Entscheidung (wichtig!)
-----------------------------------
Das Dashboard rechnet ALLE Kennzahlen und die Streich-Empfehlung selbst
(queries.py + scoring.py). Das LLM bekommt diese fertigen Zahlen und die bereits
getroffene Empfehlung und schreibt daraus nur ein **Begründungs-Memo**.

Warum so? Kleine, lokal laufende Modelle rechnen unzuverlässig, formulieren aber
gut. Indem die Entscheidung deterministisch im Code fällt und das Modell nur
*erklärt*, ist das Ergebnis reproduzierbar und vertrauenswürdig — das Modell kann
die Empfehlung nicht "verrechnen". Fällt Ollama aus, greift ein regelbasiertes
Template-Memo, damit das Dashboard immer funktioniert.

Modell-agnostisch
-----------------
Es ist kein bestimmtes Modell fest verdrahtet. Ist OLLAMA_MODEL gesetzt, wird es
genutzt; sonst wird das erste installierte Modell aus einer Präferenzliste
gewählt. So läuft es mit gemma2/gemma3, llama3.x, qwen2.5, mistral, phi3 …
"""

from __future__ import annotations

import os
import requests

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
# Leer = automatische Modellwahl (siehe pick_model).
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "").strip()

# Bevorzugte Modellfamilien (gut im Begründen), wenn nichts vorgegeben ist.
_PREFERRED = ["qwen2.5", "llama3.1", "llama3.2", "gemma2", "gemma3", "mistral", "phi3", "llama3"]

_TIMEOUT_SHORT = 3
_TIMEOUT_GEN = 90


# ── Verfügbarkeit & Modellwahl ────────────────────────────────────────────────

def list_models() -> list[str]:
    """Alle in Ollama installierten Modelle (leer, wenn Ollama nicht läuft)."""
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=_TIMEOUT_SHORT)
        if r.status_code != 200:
            return []
        return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return []


def is_available() -> bool:
    """True, wenn Ollama erreichbar ist und mindestens ein Modell bereitsteht."""
    return len(list_models()) > 0


def pick_model(preferred: str | None = None) -> str | None:
    """Wählt ein Modell: explizite Vorgabe > Präferenzliste > erstes installiertes."""
    models = list_models()
    if not models:
        return None
    target = (preferred or OLLAMA_MODEL).strip()
    if target:
        # Exakter Treffer oder Familien-Treffer (z. B. "qwen2.5" matcht "qwen2.5:7b").
        for m in models:
            if m == target or m.split(":")[0] == target.split(":")[0]:
                return m
    for fam in _PREFERRED:
        for m in models:
            if m.split(":")[0] == fam:
                return m
    return models[0]


# ── Prompt-Bau ────────────────────────────────────────────────────────────────

def _format_facts(facts: dict, impact: dict | None) -> str:
    lines = [
        f"Route: {facts.get('route')}",
        f"Vom System getroffene Empfehlung: {facts.get('recommendation')}",
        f"Streich-Score: {facts.get('cut_score'):.0f}/100 (höher = schwächer)",
        f"Haupttreiber: {facts.get('main_driver')}",
        f"Auslastung (Load Factor): {facts.get('load_factor'):.1f}%"
        f" (Netz-Ø {facts.get('network_load_factor'):.1f}%)",
        f"Umsatz: ${facts.get('revenue'):,.0f}"
        f" (Anteil am Netzumsatz {facts.get('revenue_share_pct'):.2f}%)",
        f"Ø Ticketpreis: ${facts.get('avg_price'):,.2f}"
        f" (Netz-Ø ${facts.get('network_avg_ticket'):,.2f})",
        f"Buchungen: {facts.get('bookings'):,}",
        f"Flüge: {facts.get('total_flights'):,}",
        f"Umsatz pro Flug: ${facts.get('rev_per_flight'):,.0f}",
        f"Umsatztrend (erster→letzter Monat): {facts.get('trend_pct'):+.1f}%",
    ]
    if facts.get("protected"):
        lines.append("Hinweis: Route ist als strategisch geschützt markiert "
                     "(hoher Absolutumsatz oder sehr hohe Auslastung).")
    if impact:
        lines.append(
            f"Streich-Impact: −${impact.get('revenue_lost_net'):,.0f} Netto-Umsatz "
            f"({impact.get('pct_of_network_revenue'):.2f}% des Netzes), "
            f"{impact.get('flights_freed'):,} Flüge / "
            f"{impact.get('bookings_affected'):,} Buchungen betroffen."
        )
    return "\n".join(lines)


def _build_prompt(facts: dict, impact: dict | None) -> str:
    return f"""Du bist Netzwerk-Planer einer Fluggesellschaft.
Die Analyse hat die Entscheidung BEREITS getroffen: "{facts.get('recommendation')}".
Deine Aufgabe ist NICHT zu rechnen oder die Empfehlung zu ändern, sondern sie in
einem knappen Memo zu begründen.

DATEN:
{_format_facts(facts, impact)}

Schreibe ein Entscheidungs-Memo auf Deutsch, max. 110 Wörter, Fliesstext (keine
Aufzählung). Nenne die 1–2 stärksten Gründe aus den Daten, dann das grösste
Risiko bzw. den wichtigsten Vorbehalt. Schliesse mit einem konkreten nächsten
Schritt (z. B. Frequenz reduzieren, Preis testen, in 2 Monaten erneut prüfen).
Widersprich der Empfehlung nicht."""


# ── Memo-Generierung ──────────────────────────────────────────────────────────

def generate_decision_memo(
    facts: dict,
    impact: dict | None = None,
    model: str | None = None,
) -> dict:
    """Erzeugt ein Entscheidungs-Memo. Returns {text, model, source}.

    source = "llm"      -> vom lokalen Modell geschrieben
    source = "template" -> regelbasierter Fallback (Ollama nicht verfügbar/Fehler)
    """
    chosen = pick_model(model)
    if not chosen:
        return {
            "text": build_template_memo(facts, impact),
            "model": None,
            "source": "template",
        }

    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": chosen,
                "messages": [{"role": "user", "content": _build_prompt(facts, impact)}],
                "stream": False,
                "options": {"temperature": 0.3, "num_predict": 260},
            },
            timeout=_TIMEOUT_GEN,
        )
        if resp.status_code == 200:
            text = resp.json()["message"]["content"].strip()
            if text:
                return {"text": text, "model": chosen, "source": "llm"}
        # Unerwartete Antwort -> Fallback.
        return {
            "text": build_template_memo(facts, impact),
            "model": chosen,
            "source": "template",
        }
    except Exception:
        return {
            "text": build_template_memo(facts, impact),
            "model": chosen,
            "source": "template",
        }


def build_template_memo(facts: dict, impact: dict | None = None) -> str:
    """Regelbasiertes Memo ohne LLM — immer verfügbar, deterministisch."""
    rec = facts.get("recommendation")
    route = facts.get("route")
    lf = facts.get("load_factor", 0)
    driver = facts.get("main_driver", "mehrere Kennzahlen")
    trend = facts.get("trend_pct", 0)
    share = facts.get("revenue_share_pct", 0)
    rpf = facts.get("rev_per_flight", 0)

    trend_txt = (
        f"steigender Umsatz ({trend:+.1f}%)" if trend > 5
        else f"fallender Umsatz ({trend:+.1f}%)" if trend < -5
        else "stabiler Umsatz"
    )

    if rec == "Streichen prüfen":
        head = (f"Die Route {route} ist ein Streich-Kandidat: "
                f"vor allem {driver}, Auslastung nur {lf:.1f}%, {trend_txt}. "
                f"Sie trägt lediglich {share:.2f}% zum Netzumsatz bei.")
        risk = ("Risiko: Anschluss-/Zubringerverkehr und Stammkunden könnten "
                "wegfallen — vor dem Streichen Umsteiger-Anteil prüfen.")
        step = ("Nächster Schritt: zunächst Frequenz senken und 2 Monate "
                "beobachten, statt sofort komplett zu streichen.")
    elif rec == "Beobachten":
        head = (f"Die Route {route} ist grenzwertig: {driver}, "
                f"Auslastung {lf:.1f}%, {trend_txt}.")
        if facts.get("protected"):
            head += " Sie ist wegen hohem Absolutumsatz/hoher Auslastung geschützt."
        risk = "Noch kein klares Streich-Signal, aber unterdurchschnittliche Effizienz."
        step = (f"Nächster Schritt: Preis-/Frequenztest fahren (Umsatz pro Flug "
                f"${rpf:,.0f}) und Entwicklung beobachten.")
    else:
        head = (f"Die Route {route} ist solide: Auslastung {lf:.1f}%, {trend_txt}, "
                f"Umsatzanteil {share:.2f}%.")
        risk = "Kein Handlungsdruck; Hauptrisiko wäre unnötige Kapazitätskürzung."
        step = "Nächster Schritt: beibehalten und im regulären Review mitlaufen lassen."

    impact_txt = ""
    if impact and rec == "Streichen prüfen":
        impact_txt = (f" Ein Streichen entspräche −${impact.get('revenue_lost_net'):,.0f} "
                      f"Netto-Umsatz ({impact.get('pct_of_network_revenue'):.2f}% des Netzes).")

    return f"{head} {risk} {step}{impact_txt}"
