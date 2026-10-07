"""Fachlogik: Tageswerte berechnen und das XML nach 'Tracciato unico cessione carburanti' erzeugen."""
import calendar
import datetime as dt
import os
from decimal import Decimal, ROUND_HALF_UP

from lxml import etree

from db import BASE_DIR

NS = 'http://dichiarazioni.distributoricarburanti.dogane.finanze.it'
XSD_PATH = os.path.join(BASE_DIR, 'xsd', 'DistributoriCarburanti.xsd')
CENT = Decimal('0.01')

_schema = None


def d2(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def split_iva(brutto, iva_satz):
    """Teilt einen Bruttobetrag in Imponibile und Imposta. Imponibile + Imposta == Brutto (auf den Cent)."""
    brutto = d2(brutto)
    imponibile = d2(brutto * 100 / (100 + Decimal(iva_satz)))
    return imponibile, brutto - imponibile


def month_bounds(monat):
    first = monat.replace(day=1)
    last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
    return first, last


def quell_werte(cur, first, last):
    """Treibstoff-Umsatz brutto je Tag aus der Tagesabrechnung (Liter x Tagespreis je Sorte)."""
    cur.execute(
        '''SELECT t.tag_date,
                  COALESCE(SUM(tp.curr - tp.prev), 0) AS liter,
                  COALESCE(SUM((tp.curr - tp.prev) * CASE tp.sorte
                      WHEN 'ssp' THEN t.price_ssp
                      WHEN 'd' THEN t.price_d
                      WHEN 'blu' THEN t.price_blu END), 0) AS brutto
             FROM public.tage t
             LEFT JOIN public.tag_pumps tp ON tp.tag_date = t.tag_date
            WHERE t.tag_date BETWEEN %s AND %s
            GROUP BY t.tag_date''',
        (first, last),
    )
    return {r['tag_date']: {'liter': Decimal(r['liter']), 'brutto': d2(r['brutto'])} for r in cur.fetchall()}


def monatsdaten(cur, monat):
    """Alle Tage eines Monats mit Quellwert, Korrektur und gueltigem Wert."""
    first, last = month_bounds(monat)
    cur.execute('SELECT * FROM corrispettivi.einstellungen WHERE id = 1')
    einst = cur.fetchone()
    iva_satz = Decimal(einst['iva_satz'])

    quelle = quell_werte(cur, first, last)
    cur.execute('SELECT * FROM corrispettivi.korrekturen WHERE tag_date BETWEEN %s AND %s', (first, last))
    korr = {r['tag_date']: r for r in cur.fetchall()}

    tage = []
    for day in range(1, last.day + 1):
        datum = first.replace(day=day)
        q = quelle.get(datum)
        k = korr.get(datum)
        brutto = d2(k['brutto']) if k else (q['brutto'] if q else Decimal('0.00'))
        imponibile, imposta = split_iva(brutto, iva_satz)
        tage.append({
            'datum': datum,
            'liter': q['liter'] if q else None,
            'brutto_quelle': q['brutto'] if q else None,
            'korrektur': k,
            'brutto': brutto,
            'imponibile': imponibile,
            'imposta': imposta,
        })
    return einst, tage


def pruefe_einstellungen(einst):
    fehler = []
    if not (einst['piva_gestore'].isdigit() and len(einst['piva_gestore']) == 11):
        fehler.append('Partita IVA Gestore muss genau 11 Ziffern haben.')
    if not (einst['piva_marchio'].isdigit() and len(einst['piva_marchio']) == 11):
        fehler.append('Partita IVA Marchio muss genau 11 Ziffern haben.')
    cd = einst['codice_ditta']
    if not (len(cd) == 13 and cd.startswith('IT00') and cd[4:7].isalpha() and cd[4:7].isupper()
            and cd[7:12].isdigit() and cd[12].isalpha() and cd[12].isupper()):
        fehler.append('Codice Ditta muss das Format IT00XXX00000X haben (13 Zeichen, siehe Licenza ADM).')
    return fehler


def _sub(parent, tag, text=None):
    el = etree.SubElement(parent, f'{{{NS}}}{tag}')
    if text is not None:
        el.text = str(text)
    return el


def _codice_iva(parent, tag, piva):
    el = _sub(parent, tag)
    _sub(el, 'IdPaese', 'IT')
    _sub(el, 'IdCodice', piva)


def baue_xml(einst, tage):
    """Erzeugt das (noch unsignierte) XML DatiDistributoriCarburanti fuer die uebergebenen Tage."""
    root = etree.Element(f'{{{NS}}}DatiDistributoriCarburanti', nsmap={None: NS})
    ana = _sub(root, 'AnagraficaGestoreImpiantoDiDistribuzioneStradaleDiCarburanti')
    _codice_iva(ana, 'CodiceIvaGestore', einst['piva_gestore'])
    _sub(ana, 'CodiceDittaImpiantoDiDistribuzioneStradaleDiCarburanti', einst['codice_ditta'])
    _codice_iva(ana, 'CodiceIvaMarchio', einst['piva_marchio'])

    for tag in tage:
        dg = _sub(root, 'DatiGiornalieri')
        _sub(dg, 'DataRiferimento', tag['datum'].strftime('%Y-%m-%dT00:00:00'))
        cg = _sub(dg, 'CorrispettiviGiornalieri')
        _sub(cg, 'Imponibile', f"{tag['imponibile']:.2f}")
        _sub(cg, 'Imposta', f"{tag['imposta']:.2f}")

    return etree.tostring(root, xml_declaration=True, encoding='UTF-8', pretty_print=True)


def validiere_xml(xml_bytes):
    """Prueft gegen das offizielle XSD der ADM. Liefert eine Liste von Fehlermeldungen (leer = gueltig)."""
    global _schema
    if _schema is None:
        _schema = etree.XMLSchema(etree.parse(XSD_PATH))
    doc = etree.fromstring(xml_bytes)
    if _schema.validate(doc):
        return []
    return [f'Zeile {e.line}: {e.message}' for e in _schema.error_log]


def dateiname(einst, monat, version):
    return f"CORR_CARB_{einst['codice_ditta']}_{monat:%Y-%m}_v{version}.xml"


def parse_monat(text):
    return dt.datetime.strptime(text, '%Y-%m').date()
