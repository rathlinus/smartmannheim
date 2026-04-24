# Smart Mannheim Klimamessnetz

Eine Home Assistant Integration für das [Stadtklimamessnetz Mannheim](https://smartmannheim.de/datenartikel/klimamessnetz-mannheim/) – über 100 Messstationen in der ganzen Stadt, direkt in dein Smart Home.

---

## Features

- **3 Sensoren pro Station** – Temperatur (°C), Luftfeuchtigkeit (%), Windgeschwindigkeit (m/s)
- **GPS-Pin auf der Karte** – jede Station erscheint als Device Tracker mit ihren echten Koordinaten
- **Mehrere Stationen gleichzeitig** – such und wähle beliebig viele Stationen per UI
- **Standard HA Device Classes** – funktioniert sofort mit Energie-Dashboard, Automationen, und History

---

## Installation

### Via HACS (empfohlen)

1. HACS öffnen → **Integrationen** → Menü oben rechts → **Custom repositories**
2. URL `https://github.com/rathlinus/smartmannheim.git` eintragen, Kategorie: **Integration**
3. Integration suchen und installieren
4. Home Assistant neu starten

### Manuell

1. Dieses Repository als ZIP herunterladen
2. Ordner `custom_components/smartmannheim_klima` in dein HA-Verzeichnis `config/custom_components/` kopieren
3. Home Assistant neu starten

---

## Einrichtung

1. **Einstellungen → Integrationen → Integration hinzufügen → Smart Mannheim Klimamessnetz**
2. Straßenname oder Stadtteil eingeben (z. B. `Feudenheim`, `Innenstadt`, `Käfertal`)
3. Passende Station(en) aus der Liste auswählen
4. Weitere Stationen hinzufügen oder direkt abschließen

Stationen lassen sich jederzeit unter **Einstellungen → Integrationen → Smart Mannheim Klimamessnetz → Konfigurieren** anpassen.

---

## Entitäten

Pro ausgewählter Station entstehen folgende Entitäten:

| Entität | Typ | Einheit | Aktualisierung |
|---|---|---|---|
| Temperatur | `sensor` | °C | 1 min |
| Luftfeuchtigkeit | `sensor` | % | 1 min |
| Windgeschwindigkeit | `sensor` | m/s | 10 min |
| Stationsstandort | `device_tracker` | GPS | statisch |

Alle Sensoren haben `measured_at` als Zusatzattribut (Zeitstempel der letzten Messung). Der Device Tracker platziert einen Pin auf der Karte mit den echten Stationskoordinaten – direkt nutzbar in der Lovelace Map Card.

---

## Voraussetzungen

- Home Assistant ≥ 2024.4.0
- Internetverbindung (die API läuft unter `apps.mvvsmartcities.com`)
- Keine Zugangsdaten erforderlich – die API ist öffentlich lesbar

---

## Technischer Hintergrund

Die Integration nutzt die interne Dashboard-API der MVV Smart Cities Plattform, die auch das öffentliche Mannheimer Klimadashboard antreibt. Die API wurde durch Browser-Analyse des öffentlichen Dashboards identifiziert.

**Wichtiger Hinweis:** Dies ist eine inoffizielle Integration auf Basis einer nicht dokumentierten API.

---

## Lizenz

MIT – Daten © Stadt Mannheim / Smart City Mannheim GmbH, bereitgestellt unter offener Lizenz gemäß [opendata.smartmannheim.de](https://opendata.smartmannheim.de/dataset/klimadaten-mannheim).
