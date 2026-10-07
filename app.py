import json
import os
from decimal import Decimal, InvalidOperation
from functools import wraps

from flask import Flask, Response, jsonify, request, send_from_directory

import corrispettivi as cr
from db import BASE_DIR, ENV, get_connection, init_schema

app = Flask(__name__, static_folder='static', static_url_path='/static')
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
                  erstellt_von, erstellt_am, hochgeladen_von, hochgeladen_am, ricevuta
             FROM corrispettivi.dateien WHERE monat = %s ORDER BY version DESC''',
        (m,),
    )
    dateien = cur.fetchall()
    summe = {
        'brutto': sum((t['brutto'] for t in tage), Decimal('0')),
        'imponibile': sum((t['imponibile'] for t in tage), Decimal('0')),
        'imposta': sum((t['imposta'] for t in tage), Decimal('0')),
    }
    for t in tage:
        k = t.pop('korrektur')
        t['korrektur'] = None if not k else {
            'notiz': k['notiz'], 'von': k['geaendert_von'], 'am': k['geaendert_am'],
        }
    return antwort({
        'monat': monat,
        'status': monat_status(cur, m),
        'einstellungen_fehler': cr.pruefe_einstellungen(einst),
        'tage': tage,
        'summe': summe,
        'dateien': dateien,
    })


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


# ---------- XML erzeugen / bestaetigen ----------

@app.post('/api/monat/<monat>/xml')
@db_tx
def xml_erzeugen(cur, monat):
    benutzer = benutzer_aus(request.get_json(force=True))
    m = cr.parse_monat(monat)
    pruefe_offen(cur, m)
    einst, tage = cr.monatsdaten(cur, m)
    fehler = cr.pruefe_einstellungen(einst)
    if fehler:
        raise Fehler('Stammdaten unvollständig – bitte unter „Einstellungen“ ergänzen.', details=fehler)

    xml = cr.baue_xml(einst, tage)
    fehler = cr.validiere_xml(xml)
    if fehler:
        raise Fehler('XML entspricht nicht dem ADM-Schema.', 422, fehler)

    cur.execute('SELECT COALESCE(MAX(version), 0) + 1 AS v FROM corrispettivi.dateien WHERE monat = %s', (m,))
    version = cur.fetchone()['v']
    name = cr.dateiname(einst, m, version)
    summe = {k: sum((t[k] for t in tage), Decimal('0')) for k in ('brutto', 'imponibile', 'imposta')}
    cur.execute(
        '''INSERT INTO corrispettivi.dateien
             (monat, version, dateiname, xml, summe_brutto, summe_imponibile, summe_imposta, erstellt_von)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id''',
        (m, version, name, xml.decode('utf-8'), summe['brutto'], summe['imponibile'], summe['imposta'], benutzer),
    )
    datei_id = cur.fetchone()['id']
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(os.path.join(OUTPUT_DIR, name), 'wb') as f:
        f.write(xml)
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


@app.post('/api/datei/<int:datei_id>/bestaetigen')
@db_tx
def upload_bestaetigen(cur, datei_id):
    body = request.get_json(force=True)
    benutzer = benutzer_aus(body)
    ricevuta = (body.get('ricevuta') or '').strip()
    cur.execute('SELECT monat, version, dateiname, hochgeladen_am FROM corrispettivi.dateien WHERE id = %s', (datei_id,))
    datei = cur.fetchone()
    if not datei:
        raise Fehler('Datei nicht gefunden.', 404)
    if datei['hochgeladen_am']:
        raise Fehler('Diese Datei wurde bereits als hochgeladen bestätigt.', 409)
    cur.execute('SELECT MAX(version) AS v FROM corrispettivi.dateien WHERE monat = %s', (datei['monat'],))
    if cur.fetchone()['v'] != datei['version']:
        raise Fehler('Nur die neueste Version eines Monats kann bestätigt werden.', 409)
    cur.execute(
        'UPDATE corrispettivi.dateien SET hochgeladen_von = %s, hochgeladen_am = now(), ricevuta = %s WHERE id = %s',
        (benutzer, ricevuta or None, datei_id),
    )
    cur.execute(
        '''INSERT INTO corrispettivi.monate (monat, status) VALUES (%s, 'uebermittelt')
           ON CONFLICT (monat) DO UPDATE SET status = 'uebermittelt' ''',
        (datei['monat'],),
    )
    protokolliere(cur, benutzer, 'upload_bestaetigt', datei['monat'], datei=datei['dateiname'], ricevuta=ricevuta)
    return antwort({'ok': True})


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
