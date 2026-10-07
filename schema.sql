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

-- Wer hat den Monat gemeldet? 'selbst' (ueber dieses Tool/PUDM) oder 'enilive' (Meldung durch Enilive)
ALTER TABLE corrispettivi.monate ADD COLUMN IF NOT EXISTS quelle TEXT NOT NULL DEFAULT 'selbst'
  CHECK (quelle IN ('selbst', 'enilive'));
ALTER TABLE corrispettivi.monate ADD COLUMN IF NOT EXISTS iut TEXT;
ALTER TABLE corrispettivi.monate ADD COLUMN IF NOT EXISTS gemeldet_am DATE;

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
  ricevuta TEXT,                                  -- IUT (Identificativo univoco dell'invio)
  UNIQUE (monat, version)
);
-- Momentaufnahme der gemeldeten Tageswerte, um spaetere Abweichungen zu erkennen
ALTER TABLE corrispettivi.dateien ADD COLUMN IF NOT EXISTS tage JSONB;

-- Signierte Datei und Versand ueber den ADM-Web-Service
ALTER TABLE corrispettivi.dateien ADD COLUMN IF NOT EXISTS xml_signiert TEXT;
ALTER TABLE corrispettivi.dateien ADD COLUMN IF NOT EXISTS signatur JSONB;            -- Ergebnis der Pruefung
ALTER TABLE corrispettivi.dateien ADD COLUMN IF NOT EXISTS signiert_von TEXT;
ALTER TABLE corrispettivi.dateien ADD COLUMN IF NOT EXISTS signiert_am TIMESTAMPTZ;
ALTER TABLE corrispettivi.dateien ADD COLUMN IF NOT EXISTS adm_umgebung TEXT;         -- prova | reale
ALTER TABLE corrispettivi.dateien ADD COLUMN IF NOT EXISTS adm_iut TEXT;
ALTER TABLE corrispettivi.dateien ADD COLUMN IF NOT EXISTS adm_codice TEXT;           -- Statuscode der ADM
ALTER TABLE corrispettivi.dateien ADD COLUMN IF NOT EXISTS adm_text TEXT;
ALTER TABLE corrispettivi.dateien ADD COLUMN IF NOT EXISTS adm_esito JSONB;           -- Fehler/Segnalazioni
ALTER TABLE corrispettivi.dateien ADD COLUMN IF NOT EXISTS adm_gesendet_von TEXT;
ALTER TABLE corrispettivi.dateien ADD COLUMN IF NOT EXISTS adm_gesendet_am TIMESTAMPTZ;
ALTER TABLE corrispettivi.dateien ADD COLUMN IF NOT EXISTS adm_geprueft_am TIMESTAMPTZ;

-- Aenderungsprotokoll (wer hat wann was gemacht)
CREATE TABLE IF NOT EXISTS corrispettivi.protokoll (
  id SERIAL PRIMARY KEY,
  zeit TIMESTAMPTZ NOT NULL DEFAULT now(),
  benutzer TEXT NOT NULL,
  aktion TEXT NOT NULL,
  monat DATE,
  details JSONB NOT NULL DEFAULT '{}'::jsonb
);
