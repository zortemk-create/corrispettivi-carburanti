import unittest

from hilfen import DS, original, signiere
from lxml import etree

import signatur


class SignaturTest(unittest.TestCase):
    def test_gueltige_xades_datei(self):
        orig = original()
        r = signatur.pruefe_signierte_datei(signiere(orig), orig)
        self.assertTrue(r['ok'], r['fehler'])
        self.assertEqual(r['unterzeichner']['name'], 'TEST WIESER')

    def test_fehlende_id_an_signaturevalue(self):
        orig = original()
        r = signatur.pruefe_signierte_datei(signiere(orig, mit_ids=False), orig)
        self.assertFalse(r['ok'])
        self.assertTrue(any('SignatureValue' in f for f in r['fehler']))

    def test_andere_datei_signiert(self):
        r = signatur.pruefe_signierte_datei(signiere(original(('999.00',))), original())
        self.assertFalse(r['ok'])
        self.assertTrue(any('Inhalt' in f for f in r['fehler']))

    def test_manipulierter_betrag(self):
        orig = original()
        signiert = signiere(orig).replace(b'<Imponibile>81.97</Imponibile>', b'<Imponibile>81.98</Imponibile>')
        r = signatur.pruefe_signierte_datei(signiert, orig)
        self.assertFalse(r['ok'])
        self.assertTrue(any('ungültig' in f for f in r['fehler']))

    def test_p7m_wird_erkannt(self):
        r = signatur.pruefe_signierte_datei(b'\x30\x82\x05\x00binary', original())
        self.assertFalse(r['ok'])
        self.assertIn('p7m', r['fehler'][0])

    def test_ohne_signatur(self):
        orig = original()
        r = signatur.pruefe_signierte_datei(orig, orig)
        self.assertFalse(r['ok'])
        self.assertIn('keine eingebettete', r['fehler'][0])

    def test_signatur_nicht_am_ende(self):
        orig = original()
        root = etree.fromstring(signiere(orig))
        sig = root.find(f'{DS}Signature')
        root.remove(sig)
        root.insert(1, sig)
        r = signatur.pruefe_signierte_datei(etree.tostring(root), orig)
        self.assertTrue(any('letzte Element' in f for f in r['fehler']))


if __name__ == '__main__':
    unittest.main()
