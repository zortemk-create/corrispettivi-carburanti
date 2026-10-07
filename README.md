# Corrispettivi Carburanti

Dashboard für die monatliche Meldung der Tageseinnahmen (Corrispettivi giornalieri) aus dem Verkauf
von Benzina/Gasolio an die Agenzia delle Dogane e dei Monopoli (ADM), die die Daten an die
Agenzia delle Entrate weitergibt. Ersetzt die bisherige automatische Meldung durch Enilive.

Die Werte werden automatisch aus der Datenbank der **Tagesabrechnung** gelesen
(`public.tage` / `public.tag_pumps`: Liter je Zapfsäule × Tagespreis je Sorte).

## Monatlicher Ablauf (manuell, ca. 15 Minuten)

1. Dashboard öffnen – es zeigt standardmäßig den Vormonat und die Frist.
2. Werte prüfen. Sie kommen 1:1 aus der Tagesabrechnung. Tage ohne Eintrag werden nicht gemeldet
   (grau, im Portal leer lassen). Einzelne Werte lassen sich bei Bedarf über **Ändern** überschreiben
   (mit Notiz; wird protokolliert, jederzeit zurücksetzbar).
3. Im **Portale Unico Dogane e Monopoli** (SPID/CNS) → *Servizi online* →
   *Corrispettivi Distributori Carburanti* → *Acquisizione corrispettivi* Monat/Jahr wählen und je Tag
   **Imponibile** und **Imposta** eintragen (ausgelassene Tage leer lassen). Klick auf einen Betrag im Dashboard kopiert ihn
   (Kopierformat `1234,56` oder `1234.56` wählbar).
4. *Salva* → *Invia*. Die angezeigte **IUT** im Dashboard unter **Übermittlung bestätigen** eintragen.
   Die gemeldeten Werte werden je Tag mit IUT gespeichert und der Monat gesperrt.
5. Im Portal unter *Interrogazione esiti* prüfen, dass keine Fehler gemeldet wurden.

### Korrektur nach der Meldung

**Korrektur öffnen** (mit Begründung) → Tag ändern. Das Dashboard zeigt jeden abweichenden Tag
mit der IUT, unter der er gemeldet wurde. Im Portal unter *Annullamento corrispettivi* diese IUT,
Häkchen *Corrispettivi* und die Data di riferimento angeben, danach nur diese Tage neu senden und
die neue IUT bestätigen. (Ein bereits gemeldeter Tag wird sonst mit „D001 Data di riferimento già
acquisita“ abgelehnt.)

## Voraussetzungen / Umstellung von Enilive

- Im PUDM über MAU das Profil **`dlr_distributori`** für den Gestore (oder eine beauftragte Person)
  beantragen; Details in `docs/adm/Nota_369012RU_2020-10-23_WebApplication.pdf`.
- Mit Enilive einen **Stichtag** vereinbaren, ab dem Enilive nicht mehr meldet. Doppelte Meldungen
  werden von der ADM abgelehnt bzw. führen zu Abweichungen.
- Für die Web-Anwendung ist keine digitale Signatur nötig (Login per SPID/CNS).

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
