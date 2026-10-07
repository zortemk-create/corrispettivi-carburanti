# Corrispettivi Carburanti

Erzeugt die monatliche Meldung der Tageseinnahmen (Corrispettivi giornalieri) aus dem Verkauf von
Benzina/Gasolio als XML nach dem **Tracciato unico – Cessione carburanti & Registro C/S** der
Agenzia delle Dogane e dei Monopoli (ADM) bzw. Agenzia delle Entrate.

Die Werte werden automatisch aus der Datenbank der **Tagesabrechnung** gelesen
(`public.tage` / `public.tag_pumps`: Liter je Zapfsäule × Tagespreis je Sorte).

## Ablauf

1. Dashboard öffnen, Monat wählen (Standard: Vormonat).
2. Werte prüfen. Gelb = Tag ohne Eintrag in der Tagesabrechnung (wird mit 0,00 € gemeldet).
3. Bei Bedarf einzelne Tage über **Ändern** korrigieren (mit Notiz; wird protokolliert,
   jederzeit auf den Wert der Tagesabrechnung zurücksetzbar).
4. **XML für Monat erstellen** – die Datei wird gegen das offizielle XSD geprüft, versioniert
   gespeichert (DB + Ordner `output/`) und kann heruntergeladen werden.
5. Datei signieren (XAdES-BES enveloped, siehe unten) und übermitteln.
6. **Upload bestätigen** (optional mit Ricevuta/IUT) – der Monat wird gesperrt.
   Korrekturen danach nur über **Korrektur öffnen** mit Begründung.

## Berechnung

- Corrispettivo lordo je Tag = Σ (Zählerstand neu − alt) × Tagespreis der Sorte (ssp, d, blu)
- Imponibile = lordo ÷ (1 + IVA-Satz), auf Cent gerundet; Imposta = lordo − Imponibile
- Nur Treibstoff. Nebenumsätze (Getränke, Öl, Zubehör) gehören nicht in diese Meldung.

## Installation

```powershell
pip install -r requirements.txt
copy .env.example .env   # DB-Zugang eintragen
python app.py            # http://127.0.0.1:5002
```

Beim Start wird das Schema `corrispettivi` in der Tagesabrechnung-Datenbank angelegt.
Die Tabellen der Tagesabrechnung werden nur gelesen.

Einmalig unter **Einstellungen** eintragen: Partita IVA Gestore, Codice Ditta des Impianto
(aus der Licenza ADM, Format `IT00XXX00000X`), Partita IVA Marchio (Bandiera) und IVA-Satz.

Tests: `python -m unittest discover -s tests`

## Übermittlung (wichtig)

Laut ADM-Handbuch (`docs/`) wird die Datei über den **Web-Service der ADM**
(`invioDistributoriCarburanti`) übermittelt und muss **digital signiert** sein
(XAdES-BES, enveloped, `ds:Signature` als letztes Element mit `Id`-Attribut,
Zertifikat eines qualifizierten Anbieters). Für den Web-Service braucht es zusätzlich ein
Authentifizierungs-Zertifikat aus dem PUDM (Profil `dlr_gestione_certificati_aut`).

Aktuell erzeugt das Tool die **unsignierte**, schema-gültige XML. Signieren erfolgt mit der
eigenen Signatur-Software (z.B. Firma-Digitale-Karte/Token).

### Ausbaustufe Automatisierung

- Signatur per Token/Zertifikat direkt im Tool (XAdES-BES)
- Versand über den ADM-Web-Service inkl. Abruf des Esito (`xsd/Esito.xsd`)
- Geplanter Lauf (z.B. am 1. Werktag des Monats Datei erstellen + Benachrichtigung)

## Quellen / Spezifikation (in `docs/` und `xsd/`)

- Tracciato unico cessione carburanti, Versione 20.12.2019 (Agenzia delle Entrate)
- XSD DistributoriCarburanti, Stand 09.06.2022 (ADM)
- Manuale Utente Distributori Carburante, Stand 27.12.2021 (ADM)
