# Corrispettivi Carburanti

Dashboard für die monatliche Meldung der Tageseinnahmen (Corrispettivi giornalieri) aus dem Verkauf
von Benzina/Gasolio an die Agenzia delle Dogane e dei Monopoli (ADM), die die Daten an die
Agenzia delle Entrate weitergibt. Ersetzt die bisherige automatische Meldung durch Enilive.

Die Werte werden automatisch aus der Datenbank der **Tagesabrechnung** gelesen
(`public.tage` / `public.tag_pumps`: Liter je Zapfsäule × Tagespreis je Sorte).

## Monatlicher Ablauf (manuell, ca. 15 Minuten)

1. Dashboard öffnen – es zeigt standardmäßig den Vormonat und die Frist.
2. Werte prüfen. Sie kommen 1:1 aus der Tagesabrechnung. Tage ohne Eintrag werden nicht gemeldet
   (grau, im Portal leer lassen). Die Spalte **Corrispettivo lordo** ist direkt in der Tabelle bearbeitbar
   (Imponibile/Imposta erscheinen als Vorschau); **Änderungen speichern** legt sie mit Notiz in der eigenen
   Tabelle `corrispettivi.korrekturen` ab – die Tagesabrechnung bleibt unverändert. Mit ↺ springt ein Tag auf den
   Wert der Tagesabrechnung zurück; auch für Tage ohne Eintrag lässt sich ein Betrag eintragen.
3. Im **Portale Unico Dogane e Monopoli** (SPID/CNS) → *Servizi online* →
   *Corrispettivi Distributori Carburanti* → *Acquisizione corrispettivi* Monat/Jahr wählen und je Tag
   **Imponibile** und **Imposta** eintragen (ausgelassene Tage leer lassen). Klick auf einen Betrag im Dashboard kopiert ihn
   (Kopierformat `1234,56` oder `1234.56` wählbar).
4. *Salva* → *Invia*. Die angezeigte **IUT** im Dashboard unter **Übermittlung bestätigen** eintragen.
   Die gemeldeten Werte werden je Tag mit IUT gespeichert und der Monat gesperrt.
5. Im Portal unter *Interrogazione esiti* prüfen, dass keine Fehler gemeldet wurden.

## Versand über den ADM-Web-Service

1. **XML-Datei erstellen & herunterladen** (gegen das ADM-Schema geprüft).
2. Mit der Firma remota als **XAdES-BES, enveloped** signieren. Die ADM verlangt zusätzlich ein `Id`-Attribut an
   `ds:Signature` und `ds:SignatureValue`; eine `.p7m`-Datei (CAdES) wird nicht angenommen.
3. **Signierte Datei hochladen** – `signatur.py` prüft Struktur, Id-Attribute, kryptografische Gültigkeit
   (mit dem eingebetteten Zertifikat) und dass der Inhalt exakt der erzeugten Datei entspricht.
4. **An ADM senden** – `adm.py` ruft `invioDistributoriCarburanti` mit dem Authentifizierungs-Zertifikat auf.
   Im Echtbetrieb ist eine ausdrückliche Bestätigung nötig; der Monat wird mit der IUT als gemeldet gesperrt.
5. **Status abfragen** – `selezionaStato` (REST) und bei Abschluss `recuperaEsito` (Fehler/Segnalazioni).
   Lehnt die ADM ab (197/198), wird der Monat wieder freigegeben.

Konfiguration in `.env` (Zertifikat aus PUDM → *Gestione Certificati*, Dateien im Ordner `zertifikate/`,
der von Git ausgeschlossen ist):

```
ADM_UMGEBUNG=prova          # prova = Testumgebung (addestramento), reale = Echtbetrieb
ADM_CERT_DATEI=zertifikate\<datei>.p12
ADM_CERT_PASSWORT=...
```

Als `dichiarante` wird die Partita IVA des Gestore gesendet. Endpunkte laut ADM-Handbuch 2.3 (2021):
`interoptest.adm.gov.it` (prova) bzw. `interop.adm.gov.it` (reale).

**Stand:** Gegen die echte ADM noch nicht getestet (Zertifikat fehlt). Getestet sind Nachrichtenaufbau
(gegen das WSDL-Schema), Signaturprüfung und der komplette Ablauf gegen die Simulation `tests/fake_adm.py`
(`ADM_BASIS_URL=http://127.0.0.1:5099`).

## Voraussetzungen / Umstellung von Enilive

- Im PUDM über MAU das Profil **`dlr_distributori`** für den Gestore (oder eine beauftragte Person)
  beantragen; Details in `docs/adm/Nota_369012RU_2020-10-23_WebApplication.pdf`.
- Mit Enilive einen **Stichtag** vereinbaren, ab dem Enilive nicht mehr meldet. Doppelte Meldungen
  werden von der ADM abgelehnt bzw. führen zu Abweichungen.
- Für die Web-Anwendung ist keine digitale Signatur nötig (Login per SPID/CNS).
- Stand 07.10.2026: Profile `dlr_distributori` (seit 2021) und `dlr_gestione_certificati_aut` sind freigegeben.
  `dlr_distributori` ist seit 18.03.2021 an 03618500403 delegiert (meldet für Enilive) – Delega erst nach dem
  vereinbarten Stichtag widerrufen.

## Meldestatus-Übersicht und API

Oben im Dashboard zeigt **Meldestatus** alle Monate: *Gemeldet* (mit Quelle Enilive oder dieses Tool, IUT und
Meldedatum), *Offen*, *Überfällig* (Frist = letzter Tag des Folgemonats), *Läuft noch*, *Korrektur offen*.
Monate vor dem ersten erfassten Monat sind *Nicht erfasst*. Ein Klick auf eine Zeile öffnet den Monat.

Hat Enilive einen Monat gemeldet, wird er über **Als von Enilive gemeldet markieren** (IUT + Meldedatum aus dem
Enilive-Portal) gesperrt, damit er nicht doppelt gesendet wird. September 2026 ist so erfasst
(IUT 20261005M4152744735, gemeldet am 05.10.2026).

Der Status ist auch maschinenlesbar abfragbar:

```
GET /api/uebersicht   →  { heute, monate: [ { monat, status, quelle, iut, gemeldet_am, frist,
                            tage_mit_daten, tage_gesamt, brutto, imponibile, imposta, abweichungen } ] }
GET /api/monat/2026-09 →  Tageswerte, Meldung (quelle/iut/gemeldet_am), Dateien
```

`status`: `gemeldet | offen | ueberfaellig | laufend | korrektur | nicht_erfasst | keine_daten`.
Ist `APP_PASSWORD` gesetzt, gilt HTTP Basic Auth auch für die API.

## Berechnung

- Corrispettivo lordo je Tag = Σ (Zählerstand neu − alt) × Tagespreis der Sorte (ssp, d, blu)
- Imponibile = lordo ÷ (1 + IVA-Satz), auf Cent gerundet; Imposta = lordo − Imponibile
- Nur Treibstoff. Nebenumsätze (Getränke, Öl, Zubehör) gehören nicht in diese Meldung.
- Frist bei monatlicher IVA-Liquidation: letzter Tag des Folgemonats.

## Installation

```powershell
pip install -r requirements.txt
copy .env.example .env   # DB-Zugang eintragen
python app.py            # http://127.0.0.1:5002
```

### Autostart

`autostart_einrichten.ps1` (als Administrator) legt zwei Windows-Aufgaben an:

- **CorrispettiviBackend** – startet das Dashboard beim Systemstart (Konto SYSTEM, Log in `backend.log`)
- **CorrispettiviWatchdog** – prüft alle 5 Minuten, ob das Dashboard antwortet, und startet es sonst neu
  (Log in `watchdog.log`)

Neustart von Hand: `Stop-ScheduledTask CorrispettiviBackend; Start-ScheduledTask CorrispettiviBackend`

Beim Start wird das Schema `corrispettivi` in der Tagesabrechnung-Datenbank angelegt.
Die Tabellen der Tagesabrechnung werden nur gelesen.

Einmalig unter **Einstellungen** eintragen: Partita IVA Gestore, Codice Ditta des Impianto
(aus der Licenza ADM, Format `IT00XXX00000X`), Partita IVA Marchio (Bandiera) und IVA-Satz.

Tests: `python -m unittest discover -s tests`

## XML / spätere Automatisierung

Bei jeder Bestätigung (und über **XML erstellen (Archiv)**) wird zusätzlich die XML nach dem
**Tracciato unico – Cessione carburanti** erzeugt, gegen das offizielle XSD geprüft und versioniert
abgelegt (DB + `output/`). Sie ist die Grundlage für den automatischen Versand über den
ADM-Web-Service `invioDistributoriCarburanti`. Dafür nötig: XAdES-BES-Signatur (enveloped) und ein
Authentifizierungs-Zertifikat aus dem PUDM (*Gestione Certificati*). WSDL und Esito-Spezifikation
liegen in `docs/adm/`.

## Quellen / Spezifikation (in `docs/` und `xsd/`)

- Tracciato unico cessione carburanti, Versione 20.12.2019 (Agenzia delle Entrate)
- XSD DistributoriCarburanti, Stand 09.06.2022 (ADM)
- Manuale Utente Distributori Carburante, Stand 27.12.2021 (ADM)
- Nota ADM 369012/RU vom 23.10.2020 – Web-Anwendung Corrispettivi Distributori Carburanti
- WSDL ContabilitaDistributoriCarburanti, File di Esito, Annullamento (ADM)
