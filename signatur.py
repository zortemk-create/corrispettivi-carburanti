"""Prueft eine vom Gestore signierte XML-Datei (XAdES-BES, enveloped) vor dem Versand an die ADM.

Anforderungen laut ADM-Handbuch (Abschnitt 2.3):
- XAdES-BES, Typ enveloped; ds:Signature ist das letzte Element unter der Wurzel
- Id-Attribut an ds:Signature und ds:SignatureValue ist Pflicht
"""
import base64

from cryptography import x509
from cryptography.x509.oid import NameOID
from lxml import etree
from signxml import XMLVerifier
from signxml.verifier import SignatureConfiguration

import corrispettivi as cr

DS = 'http://www.w3.org/2000/09/xmldsig#'
XADES = 'http://uri.etsi.org/01903/v1.3.2#'
ENVELOPED = 'http://www.w3.org/2000/09/xmldsig#enveloped-signature'
PARSER = etree.XMLParser(resolve_entities=False, no_network=True)


def _q(ns, tag):
    return f'{{{ns}}}{tag}'


def inhalt(root):
    """Fachlicher Inhalt einer DatiDistributoriCarburanti-Datei (ohne Signatur), zum Vergleichen."""
    ns = {'d': cr.NS}

    def text(path):
        return root.findtext(path, namespaces=ns)

    return {
        'piva_gestore': text('d:AnagraficaGestoreImpiantoDiDistribuzioneStradaleDiCarburanti/d:CodiceIvaGestore/d:IdCodice'),
        'codice_ditta': text('d:AnagraficaGestoreImpiantoDiDistribuzioneStradaleDiCarburanti/'
                             'd:CodiceDittaImpiantoDiDistribuzioneStradaleDiCarburanti'),
        'piva_marchio': text('d:AnagraficaGestoreImpiantoDiDistribuzioneStradaleDiCarburanti/d:CodiceIvaMarchio/d:IdCodice'),
        'tage': [
            (dg.findtext('d:DataRiferimento', namespaces=ns),
             dg.findtext('d:CorrispettiviGiornalieri/d:Imponibile', namespaces=ns),
             dg.findtext('d:CorrispettiviGiornalieri/d:Imposta', namespaces=ns))
            for dg in root.findall('d:DatiGiornalieri', namespaces=ns)
        ],
    }


def _name(name, oid):
    attrs = name.get_attributes_for_oid(oid)
    return attrs[0].value if attrs else None


def _zertifikat_info(cert):
    return {
        'name': _name(cert.subject, NameOID.COMMON_NAME),
        'codice_fiscale': _name(cert.subject, NameOID.SERIAL_NUMBER),
        'aussteller': _name(cert.issuer, NameOID.ORGANIZATION_NAME) or _name(cert.issuer, NameOID.COMMON_NAME),
        'gueltig_von': cert.not_valid_before_utc.isoformat(),
        'gueltig_bis': cert.not_valid_after_utc.isoformat(),
    }


def pruefe_signierte_datei(signiert, original):
    """Prueft die signierte Datei gegen die vom Tool erzeugte Original-XML.
    Liefert {'ok', 'fehler', 'hinweise', 'unterzeichner'}; ok=False bei jedem Fehler."""
    fehler, hinweise, unterzeichner = [], [], None

    def ergebnis():
        return {'ok': not fehler, 'fehler': fehler, 'hinweise': hinweise, 'unterzeichner': unterzeichner}

    kopf = signiert.lstrip()[:64]
    if not kopf.startswith(b'<'):
        fehler.append('Die Datei ist keine XML-Datei. Vermutlich wurde sie als .p7m (CAdES) signiert – '
                      'die ADM verlangt eine XML-Signatur im Format XAdES-BES (enveloped).')
        return ergebnis()
    try:
        root = etree.fromstring(signiert, parser=PARSER)
    except etree.XMLSyntaxError as e:
        fehler.append(f'Die Datei ist kein gültiges XML: {e}')
        return ergebnis()

    if root.tag != _q(cr.NS, 'DatiDistributoriCarburanti'):
        fehler.append('Die Datei ist keine Corrispettivi-Carburanti-Datei (falsches Wurzelelement).')
        return ergebnis()

    signaturen = root.findall(_q(DS, 'Signature'))
    if len(signaturen) != 1:
        fehler.append('Die Datei enthält keine eingebettete XML-Signatur (ds:Signature).' if not signaturen
                      else 'Die Datei enthält mehrere Signaturen – erwartet wird genau eine.')
        return ergebnis()
    sig = signaturen[0]
    if root[-1] is not sig:
        fehler.append('Die Signatur muss das letzte Element der Datei sein (enveloped).')
    if not sig.get('Id'):
        fehler.append('Das Element ds:Signature hat kein Id-Attribut (von der ADM verlangt).')
    sig_value = sig.find(_q(DS, 'SignatureValue'))
    if sig_value is None or not sig_value.get('Id'):
        fehler.append('Das Element ds:SignatureValue hat kein Id-Attribut (von der ADM verlangt).')
    if sig.find(f'.//{_q(XADES, "SignedProperties")}') is None:
        fehler.append('Die Signatur ist keine XAdES-Signatur (xades:SignedProperties fehlt).')

    referenzen = sig.findall(f'{_q(DS, "SignedInfo")}/{_q(DS, "Reference")}')
    ganzes_dokument = [r for r in referenzen if r.get('URI') == '']
    if not ganzes_dokument:
        fehler.append('Die Signatur umfasst nicht das ganze Dokument (Reference URI="" fehlt).')
    elif not any(t.get('Algorithm') == ENVELOPED
                 for t in ganzes_dokument[0].findall(f'{_q(DS, "Transforms")}/{_q(DS, "Transform")}')):
        fehler.append('Die Signatur ist nicht vom Typ „enveloped“.')

    # Inhalt muss exakt der erzeugten Datei entsprechen
    ohne_sig = etree.fromstring(signiert, parser=PARSER)
    ohne_sig.remove(ohne_sig.find(_q(DS, 'Signature')))
    if inhalt(ohne_sig) != inhalt(etree.fromstring(original)):
        fehler.append('Der Inhalt der signierten Datei stimmt nicht mit der erzeugten Datei überein '
                      '(falsche Datei signiert oder Werte verändert).')
    schema_fehler = cr.validiere_xml(etree.tostring(ohne_sig))
    if schema_fehler:
        fehler.extend(f'Schema: {f}' for f in schema_fehler)

    # Kryptografische Pruefung mit dem eingebetteten Zertifikat
    cert_el = sig.find(f'.//{_q(DS, "X509Certificate")}')
    if cert_el is None or not (cert_el.text or '').strip():
        hinweise.append('Die Signatur enthält kein Zertifikat (KeyInfo). Sie kann hier nicht geprüft werden; '
                        'die ADM prüft sie beim Empfang.')
        return ergebnis()
    try:
        cert = x509.load_der_x509_certificate(base64.b64decode(''.join(cert_el.text.split())))
        unterzeichner = _zertifikat_info(cert)
    except ValueError:
        fehler.append('Das eingebettete Zertifikat ist nicht lesbar.')
        return ergebnis()
    try:
        XMLVerifier().verify(signiert, x509_cert=cert,
                             expect_config=SignatureConfiguration(expect_references=True))
    except Exception as e:  # signxml wirft verschiedene InvalidInput/InvalidSignature-Typen
        fehler.append(f'Die Signatur ist ungültig: {e}')
    hinweise.append('Geprüft wurden Unversehrtheit und Inhalt. Ob das Zertifikat von einem qualifizierten '
                    'Anbieter stammt und gültig ist, prüft die ADM beim Empfang.')
    return ergebnis()
