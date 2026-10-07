import datetime as dt
import os
import sys
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import corrispettivi as cr  # noqa: E402

EINST = {'piva_gestore': '01234567890', 'codice_ditta': 'IT00BZA00001A', 'piva_marchio': '09876543210',
         'iva_satz': Decimal('22')}


def tage(monat, betraege):
    out = []
    for i, b in enumerate(betraege, start=1):
        imp, iva = cr.split_iva(Decimal(b), EINST['iva_satz'])
        out.append({'datum': monat.replace(day=i), 'imponibile': imp, 'imposta': iva})
    return out


class SplitIvaTest(unittest.TestCase):
    def test_summe_bleibt_brutto(self):
        for brutto in ['0', '0.01', '1000', '12345.67', '9999.99', '20740.55']:
            imp, iva = cr.split_iva(Decimal(brutto), Decimal('22'))
            self.assertEqual(imp + iva, Decimal(brutto).quantize(Decimal('0.01')))

    def test_22_prozent(self):
        imp, iva = cr.split_iva(Decimal('122.00'), Decimal('22'))
        self.assertEqual((imp, iva), (Decimal('100.00'), Decimal('22.00')))


class XmlTest(unittest.TestCase):
    def test_monat_ist_xsd_gueltig(self):
        monat = dt.date(2026, 9, 1)
        xml = cr.baue_xml(EINST, tage(monat, ['1000.00'] * 30))
        self.assertEqual(cr.validiere_xml(xml), [])
        self.assertIn(b'<DataRiferimento>2026-09-30T00:00:00</DataRiferimento>', xml)
        self.assertIn(b'<Imponibile>819.67</Imponibile>', xml)

    def test_tage_ohne_daten_werden_ausgelassen(self):
        monat = dt.date(2026, 9, 1)
        t = tage(monat, ['100', '200', '300'])
        t[1]['melden'] = False
        xml = cr.baue_xml(EINST, t)
        self.assertEqual(cr.validiere_xml(xml), [])
        self.assertNotIn(b'2026-09-02T', xml)
        self.assertEqual(list(cr.snapshot(t)), ['2026-09-01', '2026-09-03'])

    def test_ungueltige_ditta_wird_vom_xsd_abgelehnt(self):
        xml = cr.baue_xml({**EINST, 'codice_ditta': 'XYZ'}, tage(dt.date(2026, 9, 1), ['1']))
        self.assertTrue(cr.validiere_xml(xml))

    def test_pruefe_einstellungen(self):
        self.assertEqual(cr.pruefe_einstellungen(EINST), [])
        self.assertEqual(len(cr.pruefe_einstellungen({'piva_gestore': '', 'codice_ditta': '', 'piva_marchio': ''})), 3)


class HilfsTest(unittest.TestCase):
    def test_frist_letzter_tag_folgemonat(self):
        self.assertEqual(cr.frist(dt.date(2026, 1, 1)), dt.date(2026, 2, 28))
        self.assertEqual(cr.frist(dt.date(2026, 12, 1)), dt.date(2027, 1, 31))

    def test_gleich_ignoriert_iut(self):
        a = {'imponibile': '1.00', 'imposta': '0.22', 'iut': 'X'}
        self.assertTrue(cr.gleich(a, {'imponibile': '1.00', 'imposta': '0.22'}))
        self.assertFalse(cr.gleich(a, {'imponibile': '1.01', 'imposta': '0.22'}))
        self.assertFalse(cr.gleich(None, a))


if __name__ == '__main__':
    unittest.main()
