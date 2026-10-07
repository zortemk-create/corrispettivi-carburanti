import base64
import os
import tempfile
import unittest
from unittest import mock

from hilfen import BASE, p12
from lxml import etree

import adm

DEFINITORIO = os.path.join(BASE, 'docs', 'adm', 'wsdl', 'definitorio.xsd')

ANTWORT_INVIO = b'''<?xml version="1.0"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/">
 <soapenv:Body><out:Output xmlns:out="http://ws.sogei.it/output/">
  <out:IUT>20261203M4000000013</out:IUT>
  <out:esito><out:codice>20</out:codice><out:messaggio>Acquisito a sistema</out:messaggio></out:esito>
  <out:dataRegistrazione>2026-12-03</out:dataRegistrazione>
 </out:Output></soapenv:Body></soapenv:Envelope>'''

ESITO = b'''<Esito xmlns="http://dichiarazioni.distributoricarburanti.dogane.finanze.it">
 <dataOraRisposta>2026-12-03T10:00:00</dataOraRisposta>
 <errore><codice>D001</codice><descrizione>Data di riferimento gia' acquisita</descrizione></errore>
</Esito>'''

ANTWORT_ESITO = (b'''<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"><soapenv:Body>
 <p:recuperaEsitoResponse xmlns:p="http://service.ws.sogei.it"><recuperaEsitoReturn>
  <IUT>20261203M4000000013</IUT><esito><codice>198</codice><messaggio>Elaborazione KO: con esito</messaggio></esito>
  <data>''' + base64.b64encode(ESITO) + b'''</data><dataRegistrazione>2026-12-03</dataRegistrazione>
 </recuperaEsitoReturn></p:recuperaEsitoResponse></soapenv:Body></soapenv:Envelope>''')

FAULT = b'''<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"><soapenv:Body>
 <soapenv:Fault><faultcode>soapenv:Server</faultcode><faultstring>Utente non autorizzato</faultstring></soapenv:Fault>
</soapenv:Body></soapenv:Envelope>'''


class NachrichtenTest(unittest.TestCase):
    def test_invio_entspricht_wsdl_schema(self):
        env = etree.fromstring(adm.envelope_invio(b'<x/>', '02519250217'))
        inp = env.find(f'.//{{{adm.NS_INPUT}}}Input')
        schema = etree.XMLSchema(etree.parse(DEFINITORIO))
        self.assertTrue(schema.validate(inp), schema.error_log)
        self.assertEqual(base64.b64decode(inp.findtext(f'.//{{{adm.NS_INPUT}}}xml')), b'<x/>')

    def test_antwort_invio(self):
        r = adm.parse_risposta(ANTWORT_INVIO)
        self.assertEqual((r['iut'], r['codice']), ('20261203M4000000013', '20'))
        self.assertEqual(r['messaggi'], ['Acquisito a sistema'])

    def test_antwort_esito_mit_fehlern(self):
        r = adm.parse_risposta(ANTWORT_ESITO)
        self.assertEqual(r['codice'], '198')
        self.assertEqual(r['esito']['errori'][0]['codice'], 'D001')

    def test_soap_fault(self):
        with self.assertRaisesRegex(adm.AdmFehler, 'Utente non autorizzato'):
            adm.parse_risposta(FAULT)

    def test_stato_art(self):
        self.assertEqual([adm.stato_art(c) for c in ('20', '200', '198', '5')], ['laeuft', 'ok', 'fehler', 'fehler'])


class ClientTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cert = os.path.join(self.tmp.name, 'auth.p12')
        p12(self.cert)
        self.konfig = adm.Konfiguration({'ADM_UMGEBUNG': 'prova', 'ADM_CERT_DATEI': self.cert,
                                         'ADM_CERT_PASSWORT': 'geheim'})

    def tearDown(self):
        self.tmp.cleanup()

    def test_invio_mit_client_zertifikat_und_aufraeumen(self):
        gesehen = {}

        def fake_post(url, data, headers, cert, timeout):
            gesehen.update(url=url, headers=headers, cert=cert, existiert=all(os.path.exists(c) for c in cert))
            return mock.Mock(status_code=200, content=ANTWORT_INVIO)

        with mock.patch('adm.requests.post', fake_post):
            r = adm.AdmClient(self.konfig).invio(b'<signiert/>', '02519250217')
        self.assertEqual(r['iut'], '20261203M4000000013')
        self.assertTrue(gesehen['url'].startswith('https://interoptest.adm.gov.it/'))
        self.assertIn('ContabilitaDistributoriCarburanti', gesehen['headers']['SOAPAction'])
        self.assertTrue(gesehen['existiert'])
        self.assertFalse(any(os.path.exists(c) for c in gesehen['cert']), 'Temporäre Schlüsseldatei nicht gelöscht')

    def test_stato(self):
        with mock.patch('adm.requests.get', return_value=mock.Mock(status_code=200, text='200')):
            r = adm.AdmClient(self.konfig).stato('20261203M4000000013')
        self.assertEqual((r['codice'], r['art']), ('200', 'ok'))

    def test_falsches_passwort(self):
        k = adm.Konfiguration({'ADM_CERT_DATEI': self.cert, 'ADM_CERT_PASSWORT': 'falsch'})
        with self.assertRaisesRegex(adm.AdmFehler, 'Passwort'):
            k.zertifikat_info()

    def test_fehlende_konfiguration(self):
        with self.assertRaisesRegex(adm.AdmFehler, 'ADM_CERT_DATEI'):
            adm.AdmClient(adm.Konfiguration({}))


if __name__ == '__main__':
    unittest.main()
