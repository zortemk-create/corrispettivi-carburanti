import json
import os
import re
from decimal import Decimal, InvalidOperation
from functools import wraps

from flask import Flask, Response, jsonify, request, send_from_directory

import adm
import corrispettivi as cr
import signatur
from db import BASE_DIR, ENV, get_connection, init_schema

app = Flask(__name__, static_folder='static', static_url_path='/static')
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024
OUTPUT_DIR = os.path.join(BASE_DIR, 'output')
APP_PASSWORD = ENV.get('APP_PASSWORD', '')


class Fehler(Exception):
    def __init__(self, message, status=400, details=None):
        super().__init__(message)
        self.status = status
        self.details = details or []


@app.errorhandler(Fehler)
def _fehler(e):
    return jsonify({'error': str(e), 'details': e.details}), e.status


@app.before_request
def _auth():
    # Optionaler Passwortschutz (HTTP Basic), aktiv sobald APP_PASSWORD in .env gesetzt ist
    if not APP_PASSWORD:
        return None
    auth = request.authorization
    if auth and auth.password == APP_PASSWORD:
        return None
    return Response('Anmeldung erforderlich', 401, {'WWW-Authenticate': 'Basic realm="Corrispettivi"'})


def _json(obj):
    if isinstance(obj, Decimal):
        return f'{obj:.2f}'
    if hasattr(obj, 'isoformat'):
        return obj.isoformat()
    raise TypeError(type(obj))


def antwort(data, status=200):
    return Response(json.dumps(data, default=_json), status, mimetype='application/json')


def benutzer_aus(body):
    name = (body.get('benutzer') or '').strip()
    if not name:
        raise Fehler('Bitte Benutzernamen angeben.')
    return name


def db_tx(fn):
    """Oeffnet Verbindung + Transaktion und reicht den Cursor durch."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        conn = get_connection()
        try:
            with conn, conn.cursor() as cur:
                return fn(cur, *args, **kwargs)
        finally:
            conn.close()
    return wrapper


def protokolliere(cur, benutzer, aktion, monat=None, **details):
    cur.execute(
        'INSERT INTO corrispettivi.protokoll (benutzer, aktion, monat, details) VALUES (%s, %s, %s, %s)',
        (benutzer, aktion, monat, json.dumps(details, default=_json)),
    )


def monat_status(cur, monat):
    cur.execute('SELECT status FROM corrispettivi.monate WHERE monat = %s', (monat,))
    row = cur.fetchone()
    return row['status'] if row else 'offen'


def pruefe_offen(cur, monat):
    if monat_status(cur, monat) == 'uebermittelt':
        raise Fehler('Monat ist als übermittelt gesperrt. Zuerst „Korrektur öffnen“.', 409)


# ---------- Seiten ----------

@app.get('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')


# ---------- Einstellungen ----------

@app.get('/api/einstellungen')
@db_tx
def einstellungen_lesen(cur):
    cur.execute('SELECT piva_gestore, codice_ditta, piva_marchio, iva_satz FROM corrispettivi.einstellungen WHERE id = 1')
    return antwort(cur.fetchone())


@app.put('/api/einstellungen')
@db_tx
def einstellungen_speichern(cur):
    body = request.get_json(force=True)
    benutzer = benutzer_aus(body)
    werte = {
        'piva_gestore': (body.get('piva_gestore') or '').strip(),
        'codice_ditta': (body.get('codice_ditta') or '').strip().upper(),
        'piva_marchio': (body.get('piva_marchio') or '').strip(),
    }
    try:
        werte['iva_satz'] = Decimal(str(body.get('iva_satz', '22')).replace(',', '.'))
    except InvalidOperation:
        raise Fehler('IVA-Satz ist keine Zahl.')
    fehler = cr.pruefe_einstellungen(werte)
    if fehler:
        raise Fehler('Einstellungen ungültig.', details=fehler)
    cur.execute(
        '''UPDATE corrispettivi.einstellungen
              SET piva_gestore = %(piva_gestore)s, codice_ditta = %(codice_ditta)s,
                  piva_marchio = %(piva_marchio)s, iva_satz = %(iva_satz)s
            WHERE id = 1''',
        werte,
    )
    protokolliere(cur, benutzer, 'einstellungen', **werte)
    return antwort({'ok': True})


# ---------- Monatsansicht ----------

@app.get('/api/monat/<monat>')
@db_tx
def monat_lesen(cur, monat):
    m = cr.parse_monat(monat)
    einst, tage = cr.monatsdaten(cur, m)
    cur.execute(
        '''SELECT id, version, dateiname, summe_brutto, summe_imponibile, summe_imposta,
                  erstellt_von, erstellt_am, hochgeladen_von, hochgeladen_am, ricevuta,
                  xml_signiert IS NOT NULL AS signiert, signatur, signiert_von, signiert_am,
                  adm_umgebung, adm_iut, adm_codice, adm_text, adm_esito, adm_gesendet_von, adm_gesendet_am,
                  adm_geprueft_am
             FROM corrispettivi.dateien WHERE monat = %s ORDER BY version DESC''',
        (m,),
    )
    dateien = cur.fetchall()
    for f in dateien:
        f['adm_art'] = adm.stato_art(f['adm_codice']) if f['adm_codice'] else None
    gemeldet = letzte_meldung(cur, m)
    aktuell = cr.snapshot(tage)
    for t in tage:
        k = t.pop('korrektur')
        t['korrektur'] = None if not k else {
            'notiz': k['notiz'], 'von': k['geaendert_von'], 'am': k['geaendert_am'],
        }
        iso = t['datum'].isoformat()
        t['gemeldet'] = gemeldet.get(iso)
        t['abweichung'] = bool(gemeldet) and not cr.gleich(gemeldet.get(iso), aktuell.get(iso))
    return antwort({
        'monat': monat,
        'status': monat_status(cur, m),
        'meldung': meldung_zu(cur, m),
        'frist': cr.frist(m),
        'einstellungen_fehler': cr.pruefe_einstellungen(einst),
        'tage': tage,
        'summe': summen(tage),
        'dateien': dateien,
    })


def meldung_zu(cur, m):
    cur.execute('SELECT quelle, iut, gemeldet_am FROM corrispettivi.monate WHERE monat = %s AND iut IS NOT NULL', (m,))
    return cur.fetchone()


def letzte_meldung(cur, m):
    cur.execute(
        '''SELECT tage FROM corrispettivi.dateien
            WHERE monat = %s AND hochgeladen_am IS NOT NULL AND tage IS NOT NULL
            ORDER BY version DESC LIMIT 1''',
        (m,),
    )
    row = cur.fetchone()
    return row['tage'] if row else {}


def summen(tage):
    gemeldet = [t for t in tage if t['melden']]
    return {k: sum((t[k] for t in gemeldet), Decimal('0')) for k in ('brutto', 'imponibile', 'imposta')}


@app.put('/api/tag/<datum>')
@db_tx
def tag_korrigieren(cur, datum):
    body = request.get_json(force=True)
    benutzer = benutzer_aus(body)
    tag = cr.dt.date.fromisoformat(datum)
    pruefe_offen(cur, tag.replace(day=1))
    try:
        brutto = cr.d2(str(body.get('brutto', '')).replace(',', '.'))
    except InvalidOperation:
        raise Fehler('Betrag ist keine Zahl.')
    if brutto < 0:
        raise Fehler('Betrag darf nicht negativ sein.')
    notiz = (body.get('notiz') or '').strip()
    cur.execute('SELECT brutto FROM corrispettivi.korrekturen WHERE tag_date = %s', (tag,))
    alt = cur.fetchone()
    cur.execute(
        '''INSERT INTO corrispettivi.korrekturen (tag_date, brutto, notiz, geaendert_von)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT (tag_date) DO UPDATE SET brutto = EXCLUDED.brutto, notiz = EXCLUDED.notiz,
                geaendert_von = EXCLUDED.geaendert_von, geaendert_am = now()''',
        (tag, brutto, notiz, benutzer),
    )
    protokolliere(cur, benutzer, 'korrektur', tag.replace(day=1), tag=tag,
                  alt=alt['brutto'] if alt else None, neu=brutto, notiz=notiz)
    return antwort({'ok': True})


@app.delete('/api/tag/<datum>')
@db_tx
def tag_zuruecksetzen(cur, datum):
    benutzer = benutzer_aus(request.get_json(force=True))
    tag = cr.dt.date.fromisoformat(datum)
    pruefe_offen(cur, tag.replace(day=1))
    cur.execute('DELETE FROM corrispettivi.korrekturen WHERE tag_date = %s RETURNING brutto', (tag,))
    alt = cur.fetchone()
    if alt:
        protokolliere(cur, benutzer, 'korrektur_entfernt', tag.replace(day=1), tag=tag, alt=alt['brutto'])
    return antwort({'ok': True})


# ---------- XML erzeugen / Uebermittlung bestaetigen ----------

IUT_MUSTER = re.compile(r'^\d{8}[A-Z]\d{10}$')   # z.B. 20261005M4152744735


def neue_version(cur, m, benutzer, iut=None):
    """Erzeugt eine neue, gegen das XSD gepruefte XML-Version des Monats.
    Mit IUT wird sie zugleich als uebermittelt gespeichert (Momentaufnahme der gemeldeten Werte)."""
    einst, tage = cr.monatsdaten(cur, m)
    fehler = cr.pruefe_einstellungen(einst)
    if fehler:
        raise Fehler('Stammdaten unvollständig – bitte unter „Einstellungen“ ergänzen.', details=fehler)
    if not any(t['melden'] for t in tage):
        raise Fehler('In diesem Monat gibt es keine Tage mit Daten.')

    xml = cr.baue_xml(einst, tage)
    fehler = cr.validiere_xml(xml)
    if fehler:
        raise Fehler('XML entspricht nicht dem ADM-Schema.', 422, fehler)

    cur.execute('SELECT COALESCE(MAX(version), 0) + 1 AS v FROM corrispettivi.dateien WHERE monat = %s', (m,))
    version = cur.fetchone()['v']
    name = cr.dateiname(einst, m, version)
    summe = summen(tage)
    snap = cr.snapshot(tage)
    if iut:
        snap = snapshot_mit_iut(cur, m, snap, iut)
    cur.execute(
        '''INSERT INTO corrispettivi.dateien
             (monat, version, dateiname, xml, summe_brutto, summe_imponibile, summe_imposta, erstellt_von, tage,
              hochgeladen_von, hochgeladen_am, ricevuta)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                   %s, CASE WHEN %s::text IS NULL THEN NULL ELSE now() END, %s) RETURNING id''',
        (m, version, name, xml.decode('utf-8'), summe['brutto'], summe['imponibile'], summe['imposta'], benutzer,
         json.dumps(snap), benutzer if iut else None, iut, iut),
    )
    datei_id = cur.fetchone()['id']
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(os.path.join(OUTPUT_DIR, name), 'wb') as f:
        f.write(xml)
    return datei_id, name, summe


def snapshot_mit_iut(cur, m, snap, iut):
    """Je Tag merken, mit welcher IUT der aktuelle Wert gemeldet wurde (noetig fuer ein spaeteres Annullamento)."""
    vorher = letzte_meldung(cur, m)
    for iso, werte in snap.items():
        alt = vorher.get(iso)
        werte['iut'] = alt['iut'] if alt and alt.get('iut') and cr.gleich(alt, werte) else iut
    return snap


def markiere_uebermittelt(cur, m, iut, quelle='selbst', datum=None):
    cur.execute(
        '''INSERT INTO corrispettivi.monate (monat, status, quelle, iut, gemeldet_am)
           VALUES (%s, 'uebermittelt', %s, %s, COALESCE(%s, CURRENT_DATE))
           ON CONFLICT (monat) DO UPDATE SET status = 'uebermittelt', quelle = EXCLUDED.quelle,
                iut = EXCLUDED.iut, gemeldet_am = EXCLUDED.gemeldet_am''',
        (m, quelle, iut, datum),
    )


@app.post('/api/monat/<monat>/xml')
@db_tx
def xml_erzeugen(cur, monat):
    benutzer = benutzer_aus(request.get_json(force=True))
    m = cr.parse_monat(monat)
    pruefe_offen(cur, m)
    datei_id, name, summe = neue_version(cur, m, benutzer)
    protokolliere(cur, benutzer, 'xml_erstellt', m, datei=name, **summe)
    return antwort({'ok': True, 'id': datei_id, 'dateiname': name})


@app.get('/api/datei/<int:datei_id>')
@db_tx
def datei_download(cur, datei_id):
    cur.execute('SELECT dateiname, xml FROM corrispettivi.dateien WHERE id = %s', (datei_id,))
    row = cur.fetchone()
    if not row:
        raise Fehler('Datei nicht gefunden.', 404)
    return Response(row['xml'], mimetype='application/xml',
                    headers={'Content-Disposition': f'attachment; filename="{row["dateiname"]}"'})


@app.post('/api/monat/<monat>/bestaetigen')
@db_tx
def uebermittlung_bestaetigen(cur, monat):
    """Der Benutzer hat die Werte im ADM-Portal eingegeben und gesendet; hier wird die IUT festgehalten."""
    body = request.get_json(force=True)
    benutzer = benutzer_aus(body)
    iut = (body.get('iut') or '').strip().upper()
    if not IUT_MUSTER.match(iut):
        raise Fehler('Bitte die IUT aus dem ADM-Portal angeben (19 Zeichen, z.B. 20261102M4000000013).')
    m = cr.parse_monat(monat)
    pruefe_offen(cur, m)
    _, name, summe = neue_version(cur, m, benutzer, iut)
    markiere_uebermittelt(cur, m, iut)
    protokolliere(cur, benutzer, 'upload_bestaetigt', m, datei=name, ricevuta=iut, **summe)
    return antwort({'ok': True})


@app.post('/api/monat/<monat>/extern')
@db_tx
def extern_gemeldet(cur, monat):
    """Merker: Der Monat wurde bereits von Enilive gemeldet (nicht ueber dieses Tool)."""
    body = request.get_json(force=True)
    benutzer = benutzer_aus(body)
    iut = (body.get('iut') or '').strip().upper()
    if not IUT_MUSTER.match(iut):
        raise Fehler('Bitte die IUT angeben (19 Zeichen, z.B. 20261005M4152744735).')
    try:
        datum = cr.dt.date.fromisoformat(body.get('datum') or '')
    except ValueError:
        raise Fehler('Bitte das Datum der Meldung angeben.')
    heute = cr.dt.date.today()
    m = cr.parse_monat(monat)
    if m >= heute.replace(day=1):
        raise Fehler('Der Monat ist noch nicht abgeschlossen und kann nicht gemeldet sein.')
    if datum > heute or datum <= cr.month_bounds(m)[1]:
        raise Fehler('Das Meldedatum muss nach Monatsende und darf nicht in der Zukunft liegen.')
    pruefe_offen(cur, m)
    markiere_uebermittelt(cur, m, iut, 'enilive', datum)
    protokolliere(cur, benutzer, 'extern_gemeldet', m, quelle='enilive', iut=iut, datum=datum)
    return antwort({'ok': True})


@app.get('/api/uebersicht')
@db_tx
def uebersicht(cur):
    """Meldestatus aller Monate (auch fuer externe Abfragen gedacht)."""
    heute = cr.dt.date.today()
    cur.execute('SELECT MIN(tag_date) AS d FROM public.tage')
    erster = cur.fetchone()['d']
    cur.execute('SELECT MIN(monat) AS m FROM corrispettivi.monate')
    erfasst_ab = cur.fetchone()['m']
    cur.execute('SELECT * FROM corrispettivi.monate')
    markiert = {r['monat']: r for r in cur.fetchall()}
    monate = []
    if erster:
        m = erster.replace(day=1)
        while m <= heute.replace(day=1):
            _, tage = cr.monatsdaten(cur, m)
            mit_daten = [t for t in tage if t['melden']]
            row = markiert.get(m)
            gemeldet = letzte_meldung(cur, m)
            aktuell = cr.snapshot(tage)
            abw = sum(1 for iso in set(gemeldet) | set(aktuell) if not cr.gleich(gemeldet.get(iso), aktuell.get(iso)))                 if gemeldet else 0
            status = cr.meldestatus(m, heute, bool(row and row['status'] == 'uebermittelt'),
                                    bool(row and row['iut']), len(mit_daten), bool(erfasst_ab and m < erfasst_ab))
            s = summen(tage)
            monate.append({
                'monat': m.strftime('%Y-%m'),
                'status': status,
                'quelle': row['quelle'] if row and row['iut'] else None,
                'iut': row['iut'] if row else None,
                'gemeldet_am': row['gemeldet_am'] if row else None,
                'frist': cr.frist(m),
                'tage_mit_daten': len(mit_daten),
                'tage_gesamt': len(tage),
                'brutto': s['brutto'], 'imponibile': s['imponibile'], 'imposta': s['imposta'],
                'abweichungen': abw,
            })
            m = cr.month_bounds(m)[1] + cr.dt.timedelta(days=1)
    return antwort({'heute': heute, 'monate': monate})


# ---------- ADM-Web-Service: signierte Datei, Versand, Status ----------

def lade_datei(cur, datei_id):
    cur.execute('SELECT * FROM corrispettivi.dateien WHERE id = %s', (datei_id,))
    datei = cur.fetchone()
    if not datei:
        raise Fehler('Datei nicht gefunden.', 404)
    return datei


def pruefe_neueste(cur, datei):
    cur.execute('SELECT MAX(version) AS v FROM corrispettivi.dateien WHERE monat = %s', (datei['monat'],))
    if cur.fetchone()['v'] != datei['version']:
        raise Fehler('Nur die neueste Version eines Monats kann signiert und gesendet werden.', 409)


@app.get('/api/adm')
def adm_konfiguration():
    k = adm.Konfiguration()
    info, fehler = None, k.fehler()
    if not fehler:
        try:
            info = k.zertifikat_info()
        except adm.AdmFehler as e:
            fehler = [str(e)]
    return antwort({'umgebung': k.umgebung, 'fehler': fehler, 'zertifikat': info})


@app.post('/api/datei/<int:datei_id>/signiert')
@db_tx
def signierte_datei_hochladen(cur, datei_id):
    benutzer = benutzer_aus(request.form)
    hochgeladen = request.files.get('datei')
    if not hochgeladen:
        raise Fehler('Bitte die signierte Datei auswählen.')
    datei = lade_datei(cur, datei_id)
    pruefe_neueste(cur, datei)
    if datei['adm_iut'] and datei['adm_umgebung'] == 'reale':
        raise Fehler('Diese Datei wurde bereits an die ADM gesendet.', 409)
    inhalt = hochgeladen.read()
    ergebnis = signatur.pruefe_signierte_datei(inhalt, datei['xml'].encode('utf-8'))
    cur.execute(
        '''UPDATE corrispettivi.dateien
              SET xml_signiert = %s, signatur = %s, signiert_von = %s, signiert_am = now(),
                  adm_umgebung = NULL, adm_iut = NULL, adm_codice = NULL, adm_text = NULL, adm_esito = NULL,
                  adm_gesendet_von = NULL, adm_gesendet_am = NULL, adm_geprueft_am = NULL
            WHERE id = %s''',
        (inhalt.decode('utf-8') if ergebnis['ok'] else None, json.dumps(ergebnis), benutzer, datei_id),
    )
    protokolliere(cur, benutzer, 'signiert_hochgeladen', datei['monat'], datei=datei['dateiname'],
                  ok=ergebnis['ok'], fehler=ergebnis['fehler'])
    return antwort(ergebnis)


@app.get('/api/datei/<int:datei_id>/signiert')
@db_tx
def signierte_datei_download(cur, datei_id):
    datei = lade_datei(cur, datei_id)
    if not datei['xml_signiert']:
        raise Fehler('Keine gültige signierte Datei vorhanden.', 404)
    name = datei['dateiname'].replace('.xml', '_signiert.xml')
    return Response(datei['xml_signiert'], mimetype='application/xml',
                    headers={'Content-Disposition': f'attachment; filename="{name}"'})


@app.post('/api/datei/<int:datei_id>/senden')
@db_tx
def an_adm_senden(cur, datei_id):
    body = request.get_json(force=True)
    benutzer = benutzer_aus(body)
    datei = lade_datei(cur, datei_id)
    pruefe_neueste(cur, datei)
    if not datei['xml_signiert']:
        raise Fehler('Zuerst die signierte Datei hochladen.')
    if datei['adm_iut'] and adm.stato_art(datei['adm_codice']) != 'fehler':
        raise Fehler(f'Bereits gesendet (IUT {datei["adm_iut"]}). Status über „Status abfragen“ prüfen.', 409)
    try:
        client = adm.AdmClient()
    except adm.AdmFehler as e:
        raise Fehler(f'ADM-Web-Service nicht eingerichtet: {e}')
    echt = client.k.umgebung == 'reale'
    if echt:
        pruefe_offen(cur, datei['monat'])
        if body.get('bestaetigt') is not True:
            raise Fehler('Echtversand muss ausdrücklich bestätigt werden.')

    cur.execute('SELECT * FROM corrispettivi.einstellungen WHERE id = 1')
    einst = cur.fetchone()
    try:
        r = client.invio(datei['xml_signiert'].encode('utf-8'), adm.dichiarante(einst))
    except adm.AdmFehler as e:
        protokolliere(cur, benutzer, 'adm_senden_fehler', datei['monat'], datei=datei['dateiname'],
                      umgebung=client.k.umgebung, fehler=str(e))
        raise Fehler(str(e), 502)

    codice = r['codice'] or ''
    text = adm.STATI.get(codice) or '; '.join(r['messaggi'])
    cur.execute(
        '''UPDATE corrispettivi.dateien
              SET adm_umgebung = %s, adm_iut = %s, adm_codice = %s, adm_text = %s, adm_esito = %s,
                  adm_gesendet_von = %s, adm_gesendet_am = now()
            WHERE id = %s''',
        (client.k.umgebung, r['iut'], codice, text, json.dumps(r['esito']) if r['esito'] else None, benutzer, datei_id),
    )
    if echt and r['iut'] and adm.stato_art(codice) != 'fehler':
        snap = snapshot_mit_iut(cur, datei['monat'], datei['tage'] or {}, r['iut'])
        cur.execute(
            '''UPDATE corrispettivi.dateien SET tage = %s, hochgeladen_von = %s, hochgeladen_am = now(), ricevuta = %s
                WHERE id = %s''',
            (json.dumps(snap), benutzer, r['iut'], datei_id),
        )
        markiere_uebermittelt(cur, datei['monat'], r['iut'])
    protokolliere(cur, benutzer, 'adm_gesendet', datei['monat'], datei=datei['dateiname'],
                  umgebung=client.k.umgebung, iut=r['iut'], codice=codice, text=text)
    return antwort({'ok': adm.stato_art(codice) != 'fehler', 'iut': r['iut'], 'codice': codice, 'text': text,
                    'umgebung': client.k.umgebung})


@app.post('/api/datei/<int:datei_id>/status')
@db_tx
def adm_status(cur, datei_id):
    benutzer = benutzer_aus(request.get_json(force=True))
    datei = lade_datei(cur, datei_id)
    if not datei['adm_iut']:
        raise Fehler('Diese Datei wurde noch nicht an die ADM gesendet.')
    try:
        client = adm.AdmClient()
        if client.k.umgebung != datei['adm_umgebung']:
            raise Fehler(f'Die Datei wurde in der Umgebung „{datei["adm_umgebung"]}“ gesendet, '
                         f'eingestellt ist „{client.k.umgebung}“.')
        st = client.stato(datei['adm_iut'])
        esito = None
        if st['art'] != 'laeuft':
            esito = client.recupera_esito(datei['adm_iut']).get('esito')
    except adm.AdmFehler as e:
        raise Fehler(str(e), 502)
    cur.execute(
        '''UPDATE corrispettivi.dateien
              SET adm_codice = %s, adm_text = %s, adm_esito = COALESCE(%s, adm_esito), adm_geprueft_am = now()
            WHERE id = %s''',
        (st['codice'], st['text'], json.dumps(esito) if esito else None, datei_id),
    )
    if datei['adm_umgebung'] == 'reale' and st['art'] == 'fehler':
        # Von der ADM abgelehnt: Monat wieder freigeben, damit korrigiert und neu gesendet werden kann
        cur.execute("UPDATE corrispettivi.monate SET status = 'offen' WHERE monat = %s", (datei['monat'],))
        cur.execute('UPDATE corrispettivi.dateien SET hochgeladen_am = NULL, hochgeladen_von = NULL WHERE id = %s',
                    (datei_id,))
    protokolliere(cur, benutzer, 'adm_status', datei['monat'], datei=datei['dateiname'], iut=datei['adm_iut'],
                  codice=st['codice'], text=st['text'])
    return antwort({**st, 'esito': esito})


@app.post('/api/monat/<monat>/entsperren')
@db_tx
def monat_entsperren(cur, monat):
    body = request.get_json(force=True)
    benutzer = benutzer_aus(body)
    grund = (body.get('grund') or '').strip()
    if not grund:
        raise Fehler('Bitte einen Grund für die Korrektur angeben.')
    m = cr.parse_monat(monat)
    cur.execute("UPDATE corrispettivi.monate SET status = 'offen' WHERE monat = %s", (m,))
    protokolliere(cur, benutzer, 'korrektur_geoeffnet', m, grund=grund)
    return antwort({'ok': True})


@app.get('/api/protokoll')
@db_tx
def protokoll(cur):
    monat = request.args.get('monat')
    if monat:
        cur.execute('SELECT * FROM corrispettivi.protokoll WHERE monat = %s ORDER BY zeit DESC LIMIT 200',
                    (cr.parse_monat(monat),))
    else:
        cur.execute('SELECT * FROM corrispettivi.protokoll ORDER BY zeit DESC LIMIT 200')
    return antwort(cur.fetchall())


if __name__ == '__main__':
    init_schema()
    app.run(host=ENV.get('HOST', '127.0.0.1'), port=int(ENV.get('PORT', '5002')), debug=False)
