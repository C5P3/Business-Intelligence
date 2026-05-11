# Änderungsprotokoll — Flughafen BI Projekt

## Übersicht

Dieses Dokument hält alle Anpassungen fest, die am Datenbankinhalt und am Dashboard-Code vorgenommen wurden.

---

## 1. Datenbankbereinigung

**Datum:** 2026-05-11  
**Datenbank:** `flughafendb` (MySQL 8, lokale Instanz)  
**Durchgeführt von:** KI-Assistent (Claude)

### 1.1 Problem: Vier Flughäfen mit fehlerhaften Geodaten

**Tabelle:** `flughafen_geo`  
**Betroffene Zeilen:** 4  
**Auswirkung:** 358 Flüge (0,1 % aller Flüge) waren von der Routenanalyse ausgeschlossen oder zeigten falsche Städte- und Ländernamen.

**Ursache:** Die Koordinaten standen als DMS-Zeichenketten (`N395027 W0771627`) in der Spalte `land` statt als Dezimalwerte in `breite`/`laenge`. Die Spalten `breite` und `laenge` enthielten den Standardwert `0.00000000`, was dem Punkt (0°, 0°) im Golf von Guinea entspricht.

**Zustand vor der Bereinigung:**

| flughafen_id | name | stadt | land | breite | laenge |
|---|---|---|---|---|---|
| 4331 | GETTYSBURG & | GTY | N395027 W0771627 | 0.0 | 0.0 |
| 6993 | LITTLE GOOSE LOCK & | *(leer)* | N463460 W1180004 | 0.0 | 0.0 |
| 10037 | R & | *(leer)* | N464958 W1230529 | 0.0 | 0.0 |
| 11580 | ST FRANCIS & | *(leer)* | N405901 W0802117 | 0.0 | 0.0 |

**Koordinatenumrechnung (DMS → Dezimal):**

```
N395027  →  39° 50′ 27″  =  39 + 50/60 + 27/3600  =  39.840833
W0771627 →  77° 16′ 27″  = -(77 + 16/60 + 27/3600) = -77.274167

N463460  →  46° 34′ 60″  =  46 + 35/60            =  46.583333
W1180004 →  118° 00′ 04″ = -(118 + 0/60 + 4/3600)  = -118.001111

N464958  →  46° 49′ 58″  =  46 + 49/60 + 58/3600  =  46.832778
W1230529 →  123° 05′ 29″ = -(123 + 5/60 + 29/3600) = -123.091389

N405901  →  40° 59′ 01″  =  40 + 59/60 + 1/3600   =  40.983611
W0802117 →  80° 21′ 17″  = -(80 + 21/60 + 17/3600) = -80.354722
```

**Angewendete SQL-Updates:**

```sql
UPDATE flughafen_geo SET
  stadt  = 'GETTYSBURG',
  land   = 'UNITED STATES',
  breite =  39.840833,
  laenge = -77.274167
WHERE flughafen_id = 4331;

UPDATE flughafen_geo SET
  stadt  = 'LITTLE GOOSE',
  land   = 'UNITED STATES',
  breite =  46.583333,
  laenge = -118.001111
WHERE flughafen_id = 6993;

UPDATE flughafen_geo SET
  stadt  = 'RAINBOW FALLS',
  land   = 'UNITED STATES',
  breite =  46.832778,
  laenge = -123.091389
WHERE flughafen_id = 10037;

UPDATE flughafen_geo SET
  stadt  = 'ST FRANCIS',
  land   = 'UNITED STATES',
  breite =  40.983611,
  laenge = -80.354722
WHERE flughafen_id = 11580;
```

**Zustand nach der Bereinigung:**

| flughafen_id | stadt | land | breite | laenge |
|---|---|---|---|---|
| 4331 | GETTYSBURG | UNITED STATES | 39.8408 | -77.2742 |
| 6993 | LITTLE GOOSE | UNITED STATES | 46.5833 | -118.0011 |
| 10037 | RAINBOW FALLS | UNITED STATES | 46.8328 | -123.0914 |
| 11580 | ST FRANCIS | UNITED STATES | 40.9836 | -80.3547 |

### 1.2 Befund: Eine Buchung ohne Sitzplatznummer

**Tabelle:** `buchung`  
**Betroffene Zeile:** `buchung_id = 55094330`  
**Spalte:** `sitzplatz IS NULL`  
**Massnahme:** Keine Korrektur notwendig. Das Schema erlaubt NULL in dieser Spalte, und `sitzplatz` wird in keiner Dashboard-Abfrage verwendet.

### 1.3 Befund: Leere Tabellen (erwartet)

| Tabelle | Zeilen | Erklärung |
|---|---|---|
| `flug_log` | 0 | Änderungsprotokoll — laut README leer |
| `flughafen_erreichbar` | 0 | Erreichbarkeitsanalyse — laut README leer |

---

## 2. SQL-Anpassungen (Abfrageebene)

**Problem:** MySQL 8 hat den Modus `ONLY_FULL_GROUP_BY` standardmässig aktiviert. Alle nicht-aggregierten Spalten im `SELECT` müssen explizit im `GROUP BY` stehen.

**Betroffene Abfragen in `dashboard/queries.py`:**

| Funktion | Problem | Fix |
|---|---|---|
| `get_top_routes_revenue()` | `g1.stadt`, `g2.stadt` fehlten im `GROUP BY` | `GROUP BY f.von, f.nach, g1.stadt, g2.stadt` |
| `get_top_routes_flights()` | identisch | identisch |

**Beispiel (vorher/nachher):**

```sql
-- Vorher (Fehler: ERROR 1055 - ONLY_FULL_GROUP_BY)
GROUP BY f.von, f.nach

-- Nachher (korrekt)
GROUP BY f.von, f.nach, g1.stadt, g2.stadt
```

---

## 3. Gesamtergebnis der Datenqualitätsprüfung

| Prüfpunkt | Ergebnis |
|---|---|
| NULL-Werte in `preis`, `abflug`, `ankunft`, `flug_id`, `passagier_id` | ✓ Keine |
| Logikfehler (`ankunft` vor `abflug`) | ✓ Keine |
| Orphan-Buchungen (Buchung ohne existierenden Flug) | ✓ Keine |
| Orphan-Flüge (Flug ohne existierende Airline) | ✓ Keine |
| Flughäfen ohne Geo-Eintrag | ✓ Keine |
| Geo-Einträge ohne Flughafen | ✓ Keine |
| Passagiere ohne `passagierdetails` | ✓ Keine |
| Flugzeuge mit Kapazität ≤ 0 | ✓ Keine |
| Airlines ohne Namen oder IATA-Code | ✓ Keine |
| Flughäfen mit Koordinaten (0, 0) | ✗ 4 gefunden → **behoben** |
| `land`-Spalte mit DMS-Strings statt Ländernamen | ✗ 4 gefunden → **behoben** |
