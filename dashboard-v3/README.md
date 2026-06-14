# Dashboard V3 — Route Decision Cockpit

Entscheidungs-Dashboard auf Basis der `flughafendb`. Ziel ist nicht nur das
Anzeigen von Kennzahlen, sondern eine konkrete Handlungsempfehlung pro Route:
**streichen, beobachten oder behalten** — inklusive Simulation, was ein Streichen
kostet, und einem lokal erzeugten Begründungs-Memo.

---

## Inhalt

1. [Überblick](#1-überblick)
2. [Voraussetzungen](#2-voraussetzungen)
3. [Installation & Start](#3-installation--start)
4. [Konfiguration (Umgebungsvariablen)](#4-konfiguration-umgebungsvariablen)
5. [Bedienung — was man wo macht](#5-bedienung--was-man-wo-macht)
6. [Das lokale LLM (Ollama)](#6-das-lokale-llm-ollama)
7. [Projektstruktur](#7-projektstruktur)
8. [Fehlerbehebung](#8-fehlerbehebung)
9. [Methodische Grenzen](#9-methodische-grenzen)

---

## 1. Überblick

V1 lieferte Umsatz-/Flugstatistik, V2 eine Preis-/Auslastungsmatrix. **V3 macht
daraus einen vollständigen Entscheidungsprozess:**

- **Streich-Score (0–100)** je Route aus fünf perzentil-normalisierten Signalen
  (Auslastung, Umsatz, Umsatz pro Flug, Buchungsvolumen, Trend). Die Gewichte
  sind in der Sidebar einstellbar — die Logik ist nachvollziehbar, nicht magisch.
- **Schutzregeln (Guardrails):** umsatzstarke oder sehr gut ausgelastete Routen
  werden nie zum Streichen vorgeschlagen, um strategische Fehlentscheide zu vermeiden.
- **Impact-Simulation:** Was kostet das Streichen einer Route (oder eines ganzen
  Portfolios)? Umsatz-, Flug- und Buchungseffekt inkl. anpassbarer Umbuchungsquote.
- **Lokales LLM-Memo:** das Modell formuliert die Begründung — es rechnet nichts.

Die eigentliche Entscheidung fällt deterministisch im Code (`scoring.py`). Das
LLM erklärt sie nur. Beides läuft komplett lokal.

---

## 2. Voraussetzungen

Das Dashboard ist in drei Schichten aufgebaut. Es startet bereits mit nur der
ersten Schicht; für den **optimalen Betrieb** sollten alle drei erfüllt sein.

### Pflicht — Grundbetrieb (sonst startet nichts)

- **Python 3.10 oder neuer** (getestet mit 3.12).
- Die Pakete aus `requirements.txt`: streamlit, plotly, pandas, numpy,
  mysql-connector-python, requests, python-dotenv.
- **Empfohlen:** eine virtuelle Umgebung (`.venv`), damit `pip`, `python` und
  `streamlit` garantiert dieselbe Installation verwenden (vermeidet
  „ModuleNotFoundError"-Probleme).

Ohne die nächsten beiden Schichten läuft das Dashboard im **Demo-Modus** mit
synthetischen Daten und einem regelbasierten Memo — voll bedienbar zum Ausprobieren.

### Für Echtdaten — MySQL

- **MySQL 8** läuft lokal, die Datenbank **`flughafendb`** ist eingespielt und
  unter den `DB_*`-Einstellungen erreichbar (Standard `127.0.0.1:3306`).
- Der MySQL-Modus `ONLY_FULL_GROUP_BY` ist in allen Abfragen bereits berücksichtigt.

Ist keine DB erreichbar, schaltet das Dashboard automatisch in den Demo-Modus
(deutliches Banner oben).

### Für KI-Memos — Ollama (optional)

- **Ollama** ist installiert, ein Modell ist geladen, der Server läuft auf
  `localhost:11434` (siehe [Abschnitt 6](#6-das-lokale-llm-ollama)).
- Empfohlene Hardware je Modell: siehe Modelltabelle in Abschnitt 6.

Ist Ollama nicht erreichbar, erzeugt das Dashboard automatisch ein regelbasiertes
Memo. Das Dashboard funktioniert also auch ohne LLM.

---

## 3. Installation & Start

> **Wichtig:** `app.py` liegt im Ordner `dashboard-v3/`. Streamlit-Apps werden
> **immer** mit `streamlit run` gestartet — nicht mit `python app.py`.

### Erstmalige Einrichtung (empfohlen, mit virtueller Umgebung)

```bash
cd /Users/elia/Documents/GitHub/Alpstay/Business-Intelligence/dashboard-v3
python3 -m venv .venv          # einmalig eine isolierte Umgebung anlegen
source .venv/bin/activate      # aktivieren  (Windows: .venv\Scripts\activate)
pip install -r requirements.txt
streamlit run app.py
```

Sobald `(.venv)` vorne im Terminal-Prompt steht, zeigen `pip`, `python` und
`streamlit` alle auf dieselbe Umgebung. Nach `streamlit run` öffnet sich
automatisch ein Browser-Tab unter **http://localhost:8501** — daran erkennst du,
dass es läuft.

### Jeder weitere Start

```bash
cd /Users/elia/Documents/GitHub/Alpstay/Business-Intelligence/dashboard-v3
source .venv/bin/activate
streamlit run app.py
```

### Nur schnell ausprobieren (Demo-Modus, ohne DB/Ollama)

Einfach starten wie oben — fehlt die Datenbank, erscheint oben das Demo-Banner
und es werden synthetische Beispieldaten angezeigt. So lässt sich das komplette
UI testen, bevor MySQL oder Ollama eingerichtet sind.

---

## 4. Konfiguration (Umgebungsvariablen)

Alle Einstellungen kommen aus Umgebungsvariablen — nichts ist im Code fest verdrahtet.

| Variable          | Standard                 | Zweck |
|-------------------|--------------------------|-------|
| `DB_HOST`         | `127.0.0.1`              | MySQL-Host |
| `DB_PORT`         | `3306`                   | MySQL-Port |
| `DB_USER`         | `flughafen-user`         | MySQL-Benutzer |
| `DB_PASSWORD`     | `secret`                 | MySQL-Passwort |
| `DB_NAME`         | `flughafendb`            | Datenbankname |
| `OLLAMA_URL`      | `http://localhost:11434` | Adresse des Ollama-Servers |
| `OLLAMA_MODEL`    | *(leer = Auto-Wahl)*     | erzwingt ein bestimmtes Modell |
| `DASHBOARD_DEMO`  | `0`                      | `1` erzwingt den Demo-Modus, auch wenn eine DB läuft |

Beispiel (vor dem Start im selben Terminal setzen):

```bash
export DB_USER=mein-user
export DB_PASSWORD=mein-passwort
export OLLAMA_MODEL=qwen2.5:7b
streamlit run app.py
```

---

## 5. Bedienung — was man wo macht

### Sidebar (links) — gilt für alle Tabs

Alle Regler berechnen das Dashboard sofort neu:

- **Mindest-Flüge je Route** (5–200, Standard 20): blendet Routen mit zu wenigen
  Flügen aus (statistisch zu dünn). Niedriger = auch kleine Nischenstrecken werden
  als Streich-Kandidaten berücksichtigt.
- **Gewichtung Streich-Score** (5 Regler): wie stark jedes Schwäche-Signal zählt —
  Auslastung, Umsatz, Umsatz/Flug, Buchungsvolumen, Trend. Die Werte werden
  automatisch auf 100 % normalisiert; du kannst also frei justieren (z. B.
  Auslastung höher gewichten, wenn dir Effizienz wichtiger ist als Absolutumsatz).
- **Schwellen & Schutzregeln** (aufklappbar): ab welchem Score eine Route
  „Streichen prüfen" bzw. „Beobachten" ist, sowie die beiden Schutzregeln
  (Top-Umsatz schützen, Auslastung schützen ab).

### Tab 1 — Netzwerk-Überblick · *„Wo stehe ich?"*

Sechs KPI-Kacheln (Umsatz, Buchungen, Flüge, Routen, Ø Ticketpreis,
Netz-Auslastung) und drei farbige Karten mit Anzahl Routen und Umsatzanteil je
Empfehlung. Die Streupunkt-Landkarte zeigt jede Route nach Auslastung (x-Achse)
und Umsatz (y-Achse, logarithmisch); Punktgrösse = Flüge, Farbe = Empfehlung.
Routen **unten links** (wenig Auslastung, wenig Umsatz) sind die Streich-Kandidaten.
Rechts: Verteilung der Empfehlungen und die Umsatzkonzentration (Anteil der Top-10-Routen).
→ Einstiegspunkt, um das Netz als Ganzes zu verstehen.

### Tab 2 — Streich-Scorecard · *„Welche Routen konkret?"*

Alle Routen nach Streich-Score sortiert. Oben ein Filter nach Empfehlung
(Standard: „Streichen prüfen" + „Beobachten"), darunter ein Balkendiagramm der
Top-15-Kandidaten und die vollständige, sortierbare Tabelle mit Score, Empfehlung,
**Haupttreiber** (warum die Route schwach ist), Auslastung, Umsatz, Umsatz/Flug,
Trend, Buchungen, Flügen und einem „Geschützt"-Flag. Der Button **Scorecard als
CSV** exportiert die aktuell gefilterte Auswahl.
→ Hier identifizierst du die konkreten Kandidaten samt Hauptgrund.

### Tab 3 — Routen-Cockpit · *„Eine Route entscheiden"*

Oben die Routen-Auswahl (vorsortiert nach Score — stärkster Kandidat zuerst), dann
ein Entscheidungs-Banner mit Empfehlung, Score und Haupttreiber. Fünf Kennzahl-
Kacheln (Auslastung vs. Netz, Preis vs. Markt, Umsatz + Netzanteil, Umsatz/Flug,
Trend). Links der Monatsverlauf (Umsatz-Balken + Buchungslinie), rechts ein Radar
der fünf Schwäche-Signale, darunter die Airlines der Strecke.

Darunter die **Impact-Simulation**: ein Schieberegler „Umbuchungsquote" (Anteil der
Buchungen, der auf andere Routen wechselt) und vier Kacheln — Netto-Umsatzverlust,
frei werdende Flüge, freie Sitzplätze, betroffene Buchungen.

Ganz unten das **KI-Memo**: ein Statusbanner zeigt, ob Ollama läuft und welches
Modell verwendet wird. Der Button **Memo generieren** erstellt die Begründung
(lokales LLM oder, falls keines läuft, das Template-Memo).
→ Hier triffst du die Einzelentscheidung mit voller Begründung.

### Tab 4 — Was-wäre-wenn · *„Mehrere Routen gleichzeitig"*

Eine Mehrfachauswahl von Routen (vorbelegt mit allen „Streichen prüfen"-Routen)
und ein Umbuchungsquote-Regler. Vier Summen-Kacheln (Anzahl gestrichen,
Netto-Umsatzverlust, frei werdende Flüge, betroffene Buchungen), ein Balkendiagramm
„Umsatzverlust je Route" und ein Fazit-Satz.
→ Portfolio-Sicht: den Gesamteffekt eines Streich-Pakets aufs Netz prüfen.

### Typischer Arbeitsablauf

1. **Überblick** → Lage verstehen, Gewichte in der Sidebar nach deinen Prioritäten setzen.
2. **Scorecard** → Kandidaten herausfiltern, bei Bedarf als CSV exportieren.
3. **Cockpit** → je Kandidat Detail prüfen und ein Memo generieren.
4. **Was-wäre-wenn** → das Gesamtpaket simulieren, bevor du final entscheidest.

---

## 6. Das lokale LLM (Ollama)

### Warum dieser Ansatz

Das Dashboard berechnet **alle Zahlen und die Empfehlung selbst** (`scoring.py`).
Das LLM bekommt diese fertigen Werte und schreibt nur das Memo. Vorteile:

- **Reproduzierbar & vertrauenswürdig:** die Entscheidung kann sich nicht
  „verrechnen", weil das Modell nicht rechnet, sondern nur erklärt.
- **Robust mit kleinen Modellen:** lokale Modelle sind schwach in Arithmetik,
  aber stark im Formulieren — genau diese Stärke wird genutzt.
- **Kein Datenabfluss:** alles bleibt auf deinem Rechner.
- **Fällt das LLM aus**, erzeugt das Dashboard ein regelbasiertes Memo — es bleibt
  immer funktionsfähig.

Bewusst vermiedenes Anti-Muster: das LLM selbst SQL schreiben und Zahlen berechnen
zu lassen. Für kleine lokale Modelle ist das zu fehleranfällig.

### Schritt 1 — Ollama installieren

| System            | Befehl / Download |
|-------------------|-------------------|
| macOS             | App laden: <https://ollama.com/download/Ollama.dmg> (in *Programme* ziehen, starten) |
| macOS / Linux     | `curl -fsSL https://ollama.com/install.sh \| sh` |
| Windows           | <https://ollama.com/download/OllamaSetup.exe> |
| Homebrew          | `brew install ollama` |

Nach dem Start läuft der Server auf `http://localhost:11434` (auf dem Mac sichtbar
am Symbol in der Menüleiste). Das Dashboard spricht ihn per REST an — keine
zusätzliche Python-Bibliothek nötig.

### Schritt 2 — Ein Modell laden

Das Dashboard ist **modell-agnostisch**: es nimmt automatisch ein installiertes
Modell. Wähle nach Arbeitsspeicher (RAM):

| RAM / Maschine        | Empfehlung                    | Befehl |
|-----------------------|-------------------------------|--------|
| 8 GB                  | klein & schnell               | `ollama pull llama3.2:3b` |
| 16 GB                 | guter Kompromiss              | `ollama pull qwen2.5:7b` |
| 32 GB +               | stärkste Begründungen         | `ollama pull qwen2.5:14b` |
| Intel-Mac / nur CPU   | klein (langsamer, läuft aber) | `ollama pull llama3.2:3b` |

**`llama3.2:3b` ist die sichere Default-Wahl** — läuft überall, auch ohne GPU, und
reicht für die kurzen Memos. Gibt die Maschine mehr her, später auf `qwen2.5:7b`
wechseln (deutlich bessere Begründungen).

### Schritt 3 — testen & verbinden

```bash
ollama run llama3.2:3b "Antworte mit einem Wort: Test"   # kurzer Funktionstest
```

Danach `streamlit run app.py` starten → Tab **Routen-Cockpit** → **Memo generieren**.
Das Statusbanner zeigt, ob das Modell erkannt wurde. Erkennt es nichts, kommt
automatisch das Template-Memo.

### Modell/URL festlegen (optional)

```bash
export OLLAMA_MODEL=qwen2.5:7b           # erzwingt ein bestimmtes Modell
export OLLAMA_URL=http://localhost:11434  # falls Ollama woanders läuft
```

Ohne `OLLAMA_MODEL` wählt `llm.py` automatisch — bevorzugt gute Begründungs-Modelle
(qwen2.5, llama3.x, gemma2/3, mistral, phi3).

### Alternativen zu Ollama

**LM Studio** (GUI mit OpenAI-kompatibler lokaler API) oder **llama.cpp / llamafile**
(maximale Kontrolle, mehr Handarbeit). Für dieses Projekt ist Ollama die beste
Balance aus Einfachheit und Qualität — deshalb ist es so verdrahtet.

---

## 7. Projektstruktur

| Datei              | Zweck |
|--------------------|-------|
| `app.py`           | Streamlit-UI (4 Tabs) |
| `queries.py`       | Datenschicht: SQL + Demo-Fallback, Trend-/Effizienz-Anreicherung |
| `scoring.py`       | Entscheidungslogik: Streich-Score, Klassifikation, Impact-Simulation |
| `llm.py`           | Lokales Ollama-Memo (modell-agnostisch) + Template-Fallback |
| `demo_data.py`     | Synthetische Daten für Demo-Modus und Tests |
| `requirements.txt` | Python-Abhängigkeiten |

Saubere Trennung: Daten (`queries.py`) → Entscheidung (`scoring.py`) → Darstellung
(`app.py`) → Sprache (`llm.py`). So bleibt die Entscheidungslogik testbar und vom
LLM unabhängig.

---

## 8. Fehlerbehebung

| Symptom | Ursache & Lösung |
|---------|------------------|
| `ModuleNotFoundError: No module named 'pandas'` | Pakete fehlen oder falscher Python. In der **venv** `pip install -r requirements.txt` ausführen (siehe Abschnitt 3). |
| `streamlit run app.py` → *File does not exist: app.py* | Falscher Ordner. Erst `cd dashboard-v3`, oder `streamlit run dashboard-v3/app.py`. |
| Du hast `python app.py` ausgeführt und es passiert nichts Sinnvolles | Streamlit-Apps müssen mit `streamlit run app.py` gestartet werden. |
| `error: externally-managed-environment` beim `pip install` | System-Python ist geschützt. Lösung: venv verwenden (Abschnitt 3) — darin funktioniert `pip` normal. |
| Oben erscheint das **Demo-Banner**, obwohl MySQL läuft | DB nicht erreichbar. `DB_*`-Variablen / Zugangsdaten prüfen, MySQL gestartet?, Port 3306 offen? |
| KI-Memo sagt „Ollama nicht erreichbar" | Ollama-App/Server starten, Modell laden (`ollama pull …`), prüfen mit `curl http://localhost:11434/api/tags`. |
| `Port 8501 is already in use` | Anderen Port wählen: `streamlit run app.py --server.port 8502`. |

---

## 9. Methodische Grenzen

Die `flughafendb` enthält **keine Kostendaten**. Daher ist keine echte
Profitabilität berechenbar. Der Streich-Score ist ein *Schwäche-Index* aus Umsatz,
Auslastung und Effizienz — eine Entscheidungs**hilfe**, kein Ersatz für eine
vollständige Deckungsbeitragsrechnung. Der 3-Monats-Zeitraum (Jun–Aug 2015) macht
den Trend zudem kurzfristig; er ist deshalb standardmässig niedrig gewichtet. Die
Schutzregeln verhindern, dass strategisch wichtige Routen allein wegen schwacher
Effizienz zum Streichen vorgeschlagen werden — die finale Entscheidung bleibt beim
Menschen.
