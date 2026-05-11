import json
import mysql.connector
import pandas as pd
import anthropic
from queries import DB_CONFIG

SYSTEM_PROMPT = """Du bist ein erfahrener BI-Analyst für eine Flughafen-Betriebsdatenbank.
Beantworte alle Fragen auf Deutsch. Führe SQL-Abfragen aus, analysiere Daten und liefere klare, handlungsrelevante Erkenntnisse.

== DATENBANKSCHEMA (MySQL 8) ==

buchung          buchung_id, flug_id, sitzplatz, passagier_id, preis
flug             flug_id, flugnr, von (→flughafen_id), nach (→flughafen_id), abflug (datetime), ankunft (datetime), fluglinie_id, flugzeug_id
fluglinie        fluglinie_id, iata, firmenname, heimat_flughafen
flugzeug         flugzeug_id, kapazitaet, typ_id, fluglinie_id
flugzeug_typ     typ_id, bezeichnung, beschreibung
flughafen        flughafen_id, iata, icao, name
flughafen_geo    flughafen_id, name, stadt, land, breite, laenge
passagier        passagier_id, passnummer, vorname, nachname
passagierdetails passagier_id, geburtsdatum, geschlecht, strasse, ort, plz, land
wetterdaten      datum, zeit, station, temp, feuchtigkeit, luftdruck, wind, wetter, windrichtung
flugplan         flugnr, von, nach, abflug, ankunft, fluglinie_id, montag–sonntag (bool)

== KRITISCHE SQL-REGELN (ONLY_FULL_GROUP_BY aktiv) ==
- Alle nicht-aggregierten SELECT-Spalten MÜSSEN im GROUP BY stehen
- Routen-Queries: GROUP BY f.von, f.nach, g1.stadt, g2.stadt
- Airline-Queries: GROUP BY fl.fluglinie_id, fl.firmenname
- Geolokation-Spalte (Point/Spatial) NIEMALS verwenden – nur stadt/land aus flughafen_geo

== DATENVERFÜGBARKEIT ==
Zeitraum: Juni–August 2015 | ~303.000 Flüge | ~3,5 Mio. Buchungen | 113 Airlines | 9.854 Flughäfen

== VERHALTEN ==
- Führe mehrere Abfragen aus wenn nötig, um eine vollständige Antwort zu liefern
- Erkläre Muster, Anomalien und Zusammenhänge verständlich
- Gib konkrete, handlungsrelevante Empfehlungen
- Formatiere Zahlen übersichtlich (Tausendertrennzeichen, 2 Dezimalstellen für Beträge)
- Bei Report-Anfragen: strukturiere die Antwort mit Überschriften und Bullet Points
"""

TOOLS = [
    {
        "name": "execute_sql",
        "description": "Führt eine SQL SELECT-Abfrage auf der Flughafen-Datenbank aus und gibt die Ergebnisse zurück.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Die SQL SELECT-Abfrage (nur SELECT erlaubt)",
                },
                "description": {
                    "type": "string",
                    "description": "Kurze Beschreibung des Abfragezwecks (wird als Diagrammtitel angezeigt)",
                },
            },
            "required": ["query", "description"],
        },
    }
]

REPORT_PROMPT = """Erstelle einen vollständigen Management Report mit diesen Abschnitten:
1. **Überblick** – Gesamtumsatz, Buchungen, Ø Ticketpreis, Passagiere
2. **Top Airlines** – Top 5 nach Umsatz und Auslastungsrate (Load Factor)
3. **Top Routen** – Die 5 rentabelsten Strecken
4. **Zeitliche Trends** – Umsatz- und Flugentwicklung über den Berichtszeitraum
5. **Handlungsempfehlungen** – 3 konkrete, datenbasierte Empfehlungen

Analysiere die Daten gründlich und hebe besonders auffällige Erkenntnisse hervor."""


def _run_sql(query: str) -> dict:
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        df = pd.read_sql(query, conn)
        conn.close()
        return {
            "success": True,
            "columns": list(df.columns),
            "rows": df.head(50).to_dict(orient="records"),
            "row_count": len(df),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def run_agent(question: str, api_messages: list) -> dict:
    """
    Runs the Claude agent loop for a given question.

    Returns:
        text         – final markdown response
        queries      – list of {description, df, sql} dicts
        api_messages – updated message history for follow-up turns
    """
    client = anthropic.Anthropic()
    messages = list(api_messages) + [{"role": "user", "content": question}]
    queries: list[dict] = []

    while True:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        if response.stop_reason != "tool_use":
            break

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue

            result = _run_sql(block.input["query"])

            if result["success"] and result.get("rows"):
                queries.append(
                    {
                        "description": block.input.get("description", "Abfrageergebnis"),
                        "df": pd.DataFrame(result["rows"]),
                        "sql": block.input["query"],
                    }
                )

            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, default=str),
                }
            )

        messages += [
            {"role": "assistant", "content": response.content},
            {"role": "user", "content": tool_results},
        ]

    final_text = " ".join(b.text for b in response.content if hasattr(b, "text"))
    messages.append({"role": "assistant", "content": response.content})

    return {"text": final_text, "queries": queries, "api_messages": messages}
