"""Client fuer die Web-Services der Agenzia delle Dogane e dei Monopoli (ADM).

- invioDistributoriCarburanti (SOAP, ContabilitaDistributoriCarburanti.process)
- selezionaStato (REST, InteropRService)  -> Statuscode zu einer IUT
- recuperaEsito  (SOAP, InteropService)   -> Esito-Datei zu einer IUT

Authentifizierung per Client-Zertifikat aus dem PUDM (Gestione Certificati, .p12).
Quelle: docs/Manuale_Utente_Distributori_Carburante_2021-12-27.pdf, docs/adm/
"""
import base64
import os
import tempfile
from contextlib import contextmanager

import requests
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, pkcs12
from lxml import etree

from db import BASE_DIR, ENV

SOAP_ENV = 'http://schemas.xmlsoap.org/soap/envelope/'
NS_INPUT = 'http://distributoricarburanti.domest.sogei.it'
NS_INTEROP = 'http://service.ws.sogei.it'
SOAP_ACTION_INVIO = 'http://process.distributoricarburanti.domest.sogei.it/wsdl/ContabilitaDistributoriCarburanti'
PARSER = etree.XMLParser(resolve_entities=False, no_network=True)

HOSTS = {'prova': 'https://interoptest.adm.gov.it', 'reale': 'https://interop.adm.gov.it'}
PFAD_INVIO = '/ContabilitaDistributoriCarburantiWeb/services/ContabilitaDistributoriCarburanti'
PFAD_STATO = '/InteropRServiceWeb/services/InteropRService/selezionaStato/'
PFAD_ESITO = '/InteropServiceWEB/services/InteropService'

# Handbuch Kap. 7: Codici stato per il servizio di recupera stato o esito
STATI = {
    '0': 'Servizio non disponibile', '1': "La verifica della firma e' fallita",
    '2': "Il certificato utilizzato per la firma non e' valido", '3': "L'Autorita' di certificazione non e' ritenuta sicura",
    '4': "La verifica dell'integrita' del messaggio è fallita", '5': 'Messaggio non firmato',
    '6': 'Telematico verifica utenza - titolare certificato: fallita', '7': 'CA verifica certificato: fallita',
    '8': 'Telematico verifica firmatario - titolare certificato: fallita', '9': 'Service ID non esistente',
    '10': 'Verifica xsd: fallita', '11': 'Errore in accodamento richiesta', '12': 'Richiesta non ancora elaborata',
    '13': 'Condizioni xsd violate', '14': 'Utente non autorizzato', '15': 'Dati di input non validi',
    '16': 'Certificato autenticazione non valido', '20': 'Acquisito a sistema', '50': 'In elaborazione',
    '51': 'In elaborazione: controllo sostanziale superato', '197': 'Elaborazione KO: senza esito',
    '198': 'Elaborazione KO: con esito', '199': 'Elaborazione OK: completata senza esito finale',
    '200': 'Elaborazione OK: completata con esito finale',
}
IN_ARBEIT = {'12', '20', '50', '51'}
ERFOLG = {'199', '200'}


def stato_art(codice):
    """'laeuft' | 'ok' | 'fehler' fuer einen Statuscode."""
    codice = str(codice)
    if codice in ERFOLG:
        return 'ok'
    if codice in IN_ARBEIT:
        return 'laeuft'
    return 'fehler'


class AdmFehler(Exception):
    pass


def _lokal(el):
    return etree.QName(el).localname


def _kind(el, name):
    """Erstes Kindelement mit lokalem Namen (Namespaces der Antworten variieren je Dienst)."""
    for c in el:
        if isinstance(c.tag, str) and _lokal(c) == name:
            return c
    return None


def _suche(root, name):
    for el in root.iter():
        if isinstance(el.tag, str) and _lokal(el) == name:
            return el
    return None


# ---------- Nachrichten ----------

def envelope_invio(xml_signiert, dichiarante, service_id='invioDistributoriCarburanti'):
    env = etree.Element(f'{{{SOAP_ENV}}}Envelope', nsmap={'soapenv': SOAP_ENV, 'dc': NS_INPUT})
    etree.SubElement(env, f'{{{SOAP_ENV}}}Header')
    body = etree.SubElement(env, f'{{{SOAP_ENV}}}Body')
    inp = etree.SubElement(body, f'{{{NS_INPUT}}}Input')
    etree.SubElement(inp, f'{{{NS_INPUT}}}serviceId').text = service_id
    data = etree.SubElement(inp, f'{{{NS_INPUT}}}data')
    etree.SubElement(data, f'{{{NS_INPUT}}}xml').text = base64.b64encode(xml_signiert).decode('ascii')
    etree.SubElement(data, f'{{{NS_INPUT}}}dichiarante').text = dichiarante
    return etree.tostring(env, xml_declaration=True, encoding='UTF-8')


def envelope_esito(iut):
    env = etree.Element(f'{{{SOAP_ENV}}}Envelope', nsmap={'soapenv': SOAP_ENV, 'ser': NS_INTEROP})
    etree.SubElement(env, f'{{{SOAP_ENV}}}Header')
    body = etree.SubElement(env, f'{{{SOAP_ENV}}}Body')
    req = etree.SubElement(body, f'{{{NS_INTEROP}}}recuperaEsito')
    etree.SubElement(req, 'iut').text = iut          # Schema ohne elementFormDefault -> unqualifiziert
    return etree.tostring(env, xml_declaration=True, encoding='UTF-8')


def parse_risposta(antwort):
    """Wertet eine SOAP-Antwort (Output bzw. recuperaEsitoReturn) aus."""
    try:
        root = etree.fromstring(antwort, parser=PARSER)
    except etree.XMLSyntaxError as e:
        raise AdmFehler(f'Antwort der ADM ist kein XML: {e}')
    fault = _suche(root, 'Fault')
    if fault is not None:
        text = _suche(fault, 'faultstring')
        raise AdmFehler(f'SOAP-Fehler der ADM: {text.text if text is not None else etree.tostring(fault, encoding=str)}')
    out = _suche(root, 'Output')
    if out is None:
        out = _suche(root, 'recuperaEsitoReturn')
    if out is None:
        raise AdmFehler('Unerwartete Antwort der ADM (kein Output-Element).')
    iut = _kind(out, 'IUT')
    esito = _kind(out, 'esito')
    data = _kind(out, 'data')
    reg = _kind(out, 'dataRegistrazione')
    codice = _kind(esito, 'codice') if esito is not None else None
    return {
        'iut': iut.text.strip() if iut is not None and iut.text else None,
        'codice': codice.text.strip() if codice is not None and codice.text else None,
        'messaggi': [m.text for m in esito if _lokal(m) == 'messaggio'] if esito is not None else [],
        'esito': parse_esito(base64.b64decode(data.text)) if data is not None and data.text else None,
        'data_registrazione': reg.text if reg is not None else None,
    }


def parse_esito(xml_bytes):
    """Esito-Datei (von der ADM signiert): Fehler und Segnalazioni mit Code und Beschreibung."""
    try:
        root = etree.fromstring(xml_bytes, parser=PARSER)
    except etree.XMLSyntaxError:
        return {'roh': xml_bytes.decode('utf-8', 'replace')}

    def logs(name):
        return [{'codice': (_kind(e, 'codice').text if _kind(e, 'codice') is not None else ''),
                 'descrizione': (_kind(e, 'descrizione').text if _kind(e, 'descrizione') is not None else '')}
                for e in root.iter() if isinstance(e.tag, str) and _lokal(e) == name]
    zeit = _suche(root, 'dataOraRisposta')
    return {'data_ora': zeit.text if zeit is not None else None, 'errori': logs('errore'), 'segnalazioni': logs('segnalazione')}


# ---------- Verbindung ----------

class Konfiguration:
    def __init__(self, env=ENV):
        self.umgebung = env.get('ADM_UMGEBUNG', 'prova').strip().lower()
        datei = env.get('ADM_CERT_DATEI', '').strip()
        self.cert_datei = os.path.join(BASE_DIR, datei) if datei and not os.path.isabs(datei) else datei
        self.cert_passwort = env.get('ADM_CERT_PASSWORT', '')
        self.basis_url = env.get('ADM_BASIS_URL', '').strip() or HOSTS.get(self.umgebung)  # Override nur fuer Tests
        self.timeout = int(env.get('ADM_TIMEOUT', '60'))

    def fehler(self):
        f = []
        if self.umgebung not in HOSTS:
            f.append("ADM_UMGEBUNG muss 'prova' oder 'reale' sein.")
        if not self.cert_datei:
            f.append('ADM_CERT_DATEI ist in der .env nicht gesetzt.')
        elif not os.path.exists(self.cert_datei):
            f.append(f'Zertifikatsdatei nicht gefunden: {self.cert_datei}')
        return f

    def zertifikat_info(self):
        """Inhaber und Ablauf des Authentifizierungs-Zertifikats (ohne den Schluessel offenzulegen)."""
        key, cert, _ = self._laden()
        from signatur import _zertifikat_info
        return _zertifikat_info(cert)

    def _laden(self):
        with open(self.cert_datei, 'rb') as f:
            daten = f.read()
        try:
            key, cert, extra = pkcs12.load_key_and_certificates(daten, self.cert_passwort.encode() or None)
        except ValueError:
            raise AdmFehler('Zertifikat konnte nicht geöffnet werden (Passwort falsch oder keine .p12/.pfx-Datei).')
        if key is None or cert is None:
            raise AdmFehler('Die Zertifikatsdatei enthält keinen privaten Schlüssel.')
        return key, cert, extra or []

    @contextmanager
    def client_cert(self):
        """requests braucht PEM-Dateien: kurzlebig in einem privaten Temp-Ordner ablegen und danach loeschen."""
        key, cert, extra = self._laden()
        with tempfile.TemporaryDirectory(prefix='adm_') as tmp:
            cert_pfad, key_pfad = os.path.join(tmp, 'cert.pem'), os.path.join(tmp, 'key.pem')
            with open(cert_pfad, 'wb') as f:
                f.write(cert.public_bytes(Encoding.PEM))
                for c in extra:
                    f.write(c.public_bytes(Encoding.PEM))
            with open(key_pfad, 'wb') as f:
                f.write(key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
            yield cert_pfad, key_pfad


class AdmClient:
    def __init__(self, konfig=None):
        self.k = konfig or Konfiguration()
        fehler = self.k.fehler()
        if fehler:
            raise AdmFehler(' '.join(fehler))

    def _post(self, pfad, body, soap_action):
        headers = {'Content-Type': 'text/xml; charset=utf-8', 'SOAPAction': f'"{soap_action}"'}
        with self.k.client_cert() as cert:
            try:
                r = requests.post(self.k.basis_url + pfad, data=body, headers=headers, cert=cert, timeout=self.k.timeout)
            except requests.RequestException as e:
                raise AdmFehler(f'Verbindung zur ADM fehlgeschlagen: {e}')
        if r.status_code >= 400 and b'Fault' not in r.content:
            raise AdmFehler(f'ADM antwortet mit HTTP {r.status_code}: {r.text[:300]}')
        return parse_risposta(r.content)

    def invio(self, xml_signiert, dichiarante):
        return self._post(PFAD_INVIO, envelope_invio(xml_signiert, dichiarante), SOAP_ACTION_INVIO)

    def recupera_esito(self, iut):
        return self._post(PFAD_ESITO, envelope_esito(iut), '')

    def stato(self, iut):
        with self.k.client_cert() as cert:
            try:
                r = requests.get(self.k.basis_url + PFAD_STATO + iut, headers={'Accept': 'application/json'},
                                 cert=cert, timeout=self.k.timeout)
            except requests.RequestException as e:
                raise AdmFehler(f'Verbindung zur ADM fehlgeschlagen: {e}')
        if r.status_code == 404:
            raise AdmFehler('Für diese IUT ist bei der ADM kein Status vorhanden.')
        if r.status_code != 200:
            raise AdmFehler(f'Statusabfrage: HTTP {r.status_code} {r.text[:200]}')
        codice = r.text.strip().strip('"')
        return {'codice': codice, 'text': STATI.get(codice, 'Unbekannter Status'), 'art': stato_art(codice)}


def dichiarante(einst):
    """Dichiarante = Steuernummer des Meldepflichtigen; bei der Ditta laut ADM-Unterlagen die Partita IVA."""
    return einst['piva_gestore']

