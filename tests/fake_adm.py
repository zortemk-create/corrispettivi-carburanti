"""Simulierte ADM-Web-Services fuer lokale Durchlauftests (kein TLS, kein Zertifikat).

Start:  python tests/fake_adm.py 5099
Dashboard dagegen starten mit ADM_BASIS_URL=http://127.0.0.1:5099
Antwortet auf invio mit IUT + Code 20, auf selezionaStato mit 200, auf recuperaEsito mit Esito ohne Fehler.
Enthaelt die gesendete Datei Tage aus Januar 2026, antwortet die Simulation mit Fehler D001 (KO 198).
"""
import base64
import datetime as dt
import sys

from flask import Flask, Response, request

app = Flask(__name__)
GESENDET = {}


def soap(body):
    return Response(f'<?xml version="1.0"?><soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/">'
                    f'<soapenv:Body>{body}</soapenv:Body></soapenv:Envelope>', mimetype='text/xml')


def esito(fehler):
    err = '<errore><codice>D001</codice><descrizione>Data di riferimento gia\' acquisita</descrizione></errore>' if fehler else ''
    xml = (f'<Esito xmlns="http://dichiarazioni.distributoricarburanti.dogane.finanze.it">'
           f'<dataOraRisposta>{dt.datetime.now():%Y-%m-%dT%H:%M:%S}</dataOraRisposta>{err}</Esito>')
    return base64.b64encode(xml.encode()).decode()


@app.post('/ContabilitaDistributoriCarburantiWeb/services/ContabilitaDistributoriCarburanti')
def invio():
    iut = f'{dt.date.today():%Y%m%d}M{len(GESENDET) + 4000000001:010d}'
    datei = base64.b64decode(request.data.split(b'xml>')[1].split(b'</')[0])
    GESENDET[iut] = b'2026-01-' in datei
    return soap(f'<out:Output xmlns:out="http://ws.sogei.it/output/"><out:IUT>{iut}</out:IUT>'
                f'<out:esito><out:codice>20</out:codice><out:messaggio>Acquisito a sistema</out:messaggio></out:esito>'
                f'<out:dataRegistrazione>{dt.date.today()}</out:dataRegistrazione></out:Output>')


@app.get('/InteropRServiceWeb/services/InteropRService/selezionaStato/<iut>')
def stato(iut):
    if iut not in GESENDET:
        return Response('', 404)
    return Response('198' if GESENDET[iut] else '200', mimetype='application/json')


@app.post('/InteropServiceWEB/services/InteropService')
def recupera_esito():
    iut = request.data.split(b'<iut>')[1].split(b'</iut>')[0].decode()
    ko = GESENDET.get(iut)
    codice = '198' if ko else '200'
    return soap(f'<p:recuperaEsitoResponse xmlns:p="http://service.ws.sogei.it"><recuperaEsitoReturn>'
                f'<IUT>{iut}</IUT><esito><codice>{codice}</codice><messaggio>x</messaggio></esito>'
                f'<data>{esito(ko)}</data><dataRegistrazione>{dt.date.today()}</dataRegistrazione>'
                f'</recuperaEsitoReturn></p:recuperaEsitoResponse>')


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=int(sys.argv[1]) if len(sys.argv) > 1 else 5099)
