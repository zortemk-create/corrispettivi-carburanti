-- Corrispettivi Carburanti: eigenes Schema in der Tagesabrechnung-Datenbank.
-- Die Quelltabellen (public.tage, public.tag_pumps) werden ausschliesslich gelesen.

CREATE SCHEMA IF NOT EXISTS corrispettivi;

-- Stammdaten fuer die Anagrafica im XML
CREATE TABLE IF NOT EXISTS corrispettivi.einstellungen (
  id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  piva_gestore TEXT NOT NULL DEFAULT '',   -- Partita IVA Gestore (11 Ziffern)
  codice_ditta TEXT NOT NULL DEFAULT '',   -- Codice Ditta ADM des Impianto (IT00XXX00000X)
  piva_marchio TEXT NOT NULL DEFAULT '',   -- Partita IVA Marchio/Bandiera (11 Ziffern)
  iva_satz NUMERIC(5,2) NOT NULL DEFAULT 22.00
);
INSERT INTO corrispettivi.einstellungen (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

-- Manuelle Korrekturen. Existiert keine Zeile, gilt der Wert aus der Tagesabrechnung.
CREATE TABLE IF NOT EXISTS corrispettivi.korrekturen (
  tag_date DATE PRIMARY KEY,
  brutto NUMERIC(12,2) NOT NULL CHECK (brutto >= 0),   -- Corrispettivo lordo Benzina/Gasolio
  notiz TEXT NOT NULL DEFAULT '',
  geaendert_von TEXT NOT NULL,
  geaendert_am TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Status je Monat: 'offen' (bearbeitbar) oder 'uebermittelt' (gesperrt)
CREATE TABLE IF NOT EXISTS corrispettivi.monate (
  monat DATE PRIMARY KEY CHECK (EXTRACT(DAY FROM monat) = 1),
  status TEXT NOT NULL DEFAULT 'offen' CHECK (status IN ('offen', 'uebermittelt'))
);

-- Jede erzeugte XML-Datei wird versioniert abgelegt
CREATE TABLE IF NOT EXISTS corrispettivi.dateien (
  id SERIAL PRIMARY KEY,
  monat DATE NOT NULL,
  version INTEGER NOT NULL,
  dateiname TEXT NOT NULL,
  xml TEXT NOT NULL,
  summe_brutto NUMERIC(14,2) NOT NULL,
  summe_imponibile NUMERIC(14,2) NOT NULL,
  summe_imposta NUMERIC(14,2) NOT NULL,
  erstellt_von TEXT NOT NULL,
  erstellt_am TIMESTAMPTZ NOT NULL DEFAULT now(),
  hochgeladen_von TEXT,
  hochgeladen_am TIMESTAMPTZ,
  ricevuta TEXT,                                  -- IUT / Protokollnummer der Uebermittlung
  UNIQUE (monat, version)
);

-- Aenderungsprotokoll (wer hat wann was gemacht)
CREATE TABLE IF NOT EXISTS corrispettivi.protokoll (
  id SERIAL PRIMARY KEY,
  zeit TIMESTAMPTZ NOT NULL DEFAULT now(),
  benutzer TEXT NOT NULL,
  aktion TEXT NOT NULL,
  monat DATE,
  details JSONB NOT NULL DEFAULT '{}'::jsonb
);
