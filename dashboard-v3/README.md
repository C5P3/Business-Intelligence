# Dashboard V3 — Route Decision Cockpit

Entscheidungs-Dashboard auf Basis der `flughafendb`. Ziel ist nicht nur das
Anzeigen von Kennzahlen, sondern eine konkrete Handlungsempfehlung pro Route:
**streichen, beobachten oder behalten** — inklusive Simulation, was ein Streichen
kostet, und einem lokal erzeugten Begründungs-Memo.

## Was V3 gegenüber V1/V2 neu macht

V2 zeigt eine Preis-/Auslastungsmatrix. V3 baut darauf einen vollständigen
Entscheidungsprozess:

- **Streich-Score (0–100)** je Route aus fünf perzentil-normalisierten Signalen
  (Auslastung, Umsatz, Umsatz pro Flug, Buchungsvolumen, Trend). Gewichte sind
  in der Sidebar einstellbar — die Logik ist nachvollziehbar, nicht magisch.
- **Schutzregeln (Guardrails):** umsatzstarke oder sehr gut ausgelastete Routen
  werden nie zum Streichen vorgeschlagen, um strategische Fehlentscheide zu
  vermeiden.
- **Impact-Simulation:** Was kostet das Streichen einer Route (oder eines ganzen
  Portfolios)? Umsatz-, Flug- und Buchungseffekt inkl. anpassbarer Umbuchungsquote.
- **Lokales LLM-Memo:** das Modell formuliert die Begründung — es rechnet nichts.

## Schnellstart

```bash
cd dashboard-v3
pip install -r requirements.txt
streamlit run app.py
```

Ohne laufende Datenbank startet das Dashboard automatisch im **Demo-Modus** mit
synthetischen Daten (deutlich gekennzeichnet), damit du das UI sofort siehst.

### Datenbank anbinden

Die Verbindungsdaten kommen aus Umgebungsvariablen (Default in Klammern):

```bash
export DB_HOST=127.0.0.1      # (127.0.0.1)
export DB_PORT=3306           # (3306)
export DB_USER=flughafen-user # (flughafen-user)
export DB_PASSWORD=secret     # (secret)
export DB_NAME=flughafendb    # (flughafendb)
```

Demo-Modus erzwingen (auch wenn eine DB läuft): `export DASHBOARD_DEMO=1`.

---

## Das lokale LLM — Architektur & Einrichtung

Das war deine offene Frage. Hier die Empfehlung und die Schritte.

### Warum dieser Ansatz (wichtig)

Das Dashboard berechnet **alle Zahlen und die Empfehlung selbst** (in `scoring.py`).
Das LLM bekommt diese fertigen Werte und schreibt nur das Memo. Vorteile:

- **Reproduzierbar & vertrauenswürdig:** die Entscheidung kann sich nicht
  „verrechnen", weil das Modell nicht rechnet, sondern nur erklärt.
- **Robust mit kleinen Modellen:** lokale Modelle sind schwach in Arithmetik,
  aber stark im Formulieren — genau diese Stärke wird genutzt.
- **Kein Datenabfluss:** alles bleibt auf deinem Rechner.
- **Fällt das LLM aus**, erzeugt das Dashboard ein regelbasiertes Memo. Es bleibt
  also immer funktionsfähig.

Anti-Muster, das wir bewusst vermeiden: das LLM selbst SQL schreiben und Zahlen
berechnen zu lassen (wie der Cloud-Agent in V1). Lokal-klein ist das zu fehleranfällig.

### Schritt 1 — Ollama installieren

Ollama ist der einfachste Weg, ein lokales LLM als kleinen HTTP-Server zu betreiben.

- **macOS / Windows:** Installer von <https://ollama.com/download>
- **Linux:** `curl -fsSL https://ollama.com/install.sh | sh`

Ollama startet einen lokalen Server auf `http://localhost:11434`. Das Dashboard
spricht ihn per REST an (`llm.py`) — keine zusätzliche Python-Bibliothek nötig.

### Schritt 2 — Ein Modell laden

Das Dashboard ist **modell-agnostisch**: es nimmt automatisch ein installiertes
Modell. Wähle nach Arbeitsspeicher (RAM):

| RAM / Maschine            | Empfehlung                      | Befehl |
|---------------------------|---------------------------------|--------|
| 8 GB                      | klein & schnell                 | `ollama pull llama3.2:3b` |
| 16 GB                     | guter Kompromiss                | `ollama pull qwen2.5:7b` |
| 32 GB +                   | stärkste Begründungen           | `ollama pull qwen2.5:14b` |
| Intel-Mac / nur CPU       | klein (langsamer, aber läuft)   | `ollama pull llama3.2:3b` |

Da deine Hardware noch offen ist: **`llama3.2:3b` ist die sichere Default-Wahl** —
läuft überall, auch ohne GPU, und reicht für 110-Wörter-Memos. Wenn die Maschine
mehr hergibt, später auf `qwen2.5:7b` wechseln (deutlich bessere Begründungen).

### Schritt 3 — starten

```bash
ollama serve              # Server starten (läuft er schon, einfach weiter)
ollama pull llama3.2:3b   # Modell einmalig herunterladen
streamlit run app.py      # Dashboard -> Tab „Routen-Cockpit" -> „Memo generieren"
```

Im Tab „Routen-Cockpit" zeigt ein Statusbanner, ob Ollama erkannt wurde und welches
Modell verwendet wird. Erkennt es nichts, kommt automatisch das Template-Memo.

### Modell festlegen oder URL ändern (optional)

```bash
export OLLAMA_MODEL=qwen2.5:7b          # erzwingt ein bestimmtes Modell
export OLLAMA_URL=http://localhost:11434 # falls Ollama woanders läuft
```

Ohne `OLLAMA_MODEL` wählt `llm.py` automatisch — bevorzugt werden gute
Begründungs-Modelle (qwen2.5, llama3.x, gemma2/3, mistral, phi3).

### Alternativen zu Ollama

- **LM Studio** (GUI): bietet ebenfalls eine OpenAI-kompatible lokale API. Dann
  in `llm.py` Endpoint/Aufruf anpassen.
- **llama.cpp / llamafile:** maximale Kontrolle, mehr Handarbeit.

Für dieses Projekt ist Ollama die beste Balance aus Einfachheit und Qualität —
deshalb ist es so verdrahtet.

---

## Dateien

| Datei           | Zweck |
|-----------------|-------|
| `app.py`        | Streamlit-UI (4 Tabs) |
| `queries.py`    | Datenschicht: SQL + Demo-Fallback, Trend-/Effizienz-Anreicherung |
| `scoring.py`    | Entscheidungslogik: Streich-Score, Klassifikation, Impact-Simulation |
| `llm.py`        | Lokales Ollama-Memo (modell-agnostisch) + Template-Fallback |
| `demo_data.py`  | Synthetische Daten für Demo-Modus und Tests |
| `requirements.txt` | Abhängigkeiten |

## Methodische Grenzen (bewusst transparent)

Die `flughafendb` enthält **keine Kostendaten**. Daher ist keine echte
Profitabilität berechenbar. Der Streich-Score ist ein *Schwäche-Index* aus
Umsatz, Auslastung und Effizienz — eine Entscheidungs**hilfe**, kein Ersatz für
eine vollständige Deckungsbeitragsrechnung. Der 3-Monats-Zeitraum (Jun–Aug 2015)
macht den Trend zudem kurzfristig; er ist deshalb standardmässig niedrig gewichtet.
