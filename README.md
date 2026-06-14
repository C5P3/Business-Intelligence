# Business Intelligence — FlughafenDB

Entscheidungs-Dashboard zur Analyse von Flugrouten auf Basis der Datenbank
`flughafendb`. Ziel: aus den Daten ableiten, welche Routen **gestrichen,
beobachtet oder behalten** werden sollten.

## Aktives Dashboard

Das Dashboard liegt in **[`dashboard-v3/`](dashboard-v3/)** (Streamlit + lokales
LLM). Voraussetzungen, Start und Bedienung stehen ausführlich in der
**[README von dashboard-v3](dashboard-v3/README.md)**.

Schnellstart:

```bash
cd dashboard-v3
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Ohne laufende Datenbank startet das Dashboard im Demo-Modus mit Beispieldaten.

## Struktur

- `dashboard-v3/` — Route Decision Cockpit (Streich-Score, Impact-Simulation, KI-Memo)
- `data/` — Datensatz, DB-Konnektoren, Schema (lokal vorhanden, via `.gitignore` nicht im Repo)
- `CHANGES.md` — Protokoll der Datenbankbereinigung

Frühere Versionen (Dashboard V1 und V2) wurden entfernt; sie bleiben über die
Git-Historie abrufbar.
