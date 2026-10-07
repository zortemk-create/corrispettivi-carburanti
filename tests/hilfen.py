"""Test-Hilfen: selbstsignierte Zertifikate und XAdES-signierte Beispieldateien."""
import datetime as dt
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cryptography import x509  # noqa: E402
from cryptography.hazmat.primitives import hashes  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from cryptography.hazmat.primitives.serialization import BestAvailableEncryption, pkcs12  # noqa: E402
from cryptography.x509.oid import NameOID  # noqa: E402
from lxml import etree  # noqa: E402
from signxml.xades import XAdESSigner  # noqa: E402

import corrispettivi as cr  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EINST = {'piva_gestore': '02519250217', 'codice_ditta': 'IT00BZY00173P', 'piva_marchio': '11403240960'}
DS = '{http://www.w3.org/2000/09/xmldsig#}'


def schluessel_und_zertifikat(cn='TEST WIESER'):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn),
                      x509.NameAttribute(NameOID.SERIAL_NUMBER, 'TINIT-TEST')])
    jetzt = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(1).not_valid_before(jetzt).not_valid_after(jetzt + dt.timedelta(days=1))
            .sign(key, hashes.SHA256()))
    return key, cert


def p12(pfad, passwort=b'geheim'):
    key, cert = schluessel_und_zertifikat('TEST ADM AUTH')
    with open(pfad, 'wb') as f:
        f.write(pkcs12.serialize_key_and_certificates(b'test', key, cert, None, BestAvailableEncryption(passwort)))


def original(betraege=('100.00', '200.00')):
    tage = []
    for i, b in enumerate(betraege, start=1):
        imp, iva = cr.split_iva(Decimal(b), Decimal('22'))
        tage.append({'datum': dt.date(2026, 11, i), 'imponibile': imp, 'imposta': iva})
    return cr.baue_xml(EINST, tage)


def signiere(xml_bytes, mit_ids=True):
    key, cert = schluessel_und_zertifikat()
    root = XAdESSigner().sign(etree.fromstring(xml_bytes), key=key, cert=[cert])
    if mit_ids:
        # SignatureValue ist nicht Teil von SignedInfo: Id nachtraeglich setzen bricht die Signatur nicht
        root.find(f'{DS}Signature/{DS}SignatureValue').set('Id', 'SigVal-1')
    return etree.tostring(root, xml_declaration=True, encoding='UTF-8')
