import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
import tempfile

from aos_catalogue_resolver import Catalogue, CatalogueResolver


def write_cat(folder, filename, xml):
    path = Path(folder) / filename
    path.write_text(xml, encoding="utf-8")
    return Catalogue.load(path)


class ResolverTests(unittest.TestCase):
    def test_cross_catalogue_link_preserves_importer_cost_and_target_profile(self):
        with tempfile.TemporaryDirectory() as d:
            lib = write_cat(d, "Library.cat", """<catalogue id="lib" name="Library">
              <selectionEntry id="unit-1" name="Iron Guard" type="unit">
                <profiles><profile id="p1" name="Iron Guard" typeName="Unit">
                  <characteristics><characteristic name="Move">4&quot;</characteristic></characteristics>
                </profile></profiles>
              </selectionEntry>
            </catalogue>""")
            army = write_cat(d, "Army.cat", """<catalogue id="army" name="Army">
              <entryLinks><entryLink id="l1" name="Iron Guard" targetId="unit-1" type="selectionEntry">
                <costs><cost name="pts" typeId="pts" value="100"/></costs>
              </entryLink></entryLinks>
            </catalogue>""")
            report = CatalogueResolver([army, lib]).report(army)
            link = report["roots"][0]
            self.assertTrue(link["resolved"])
            self.assertEqual(link["costs"][0].find("cost").get("value"), "100")
            self.assertEqual(link["target"]["profiles"][0]["characteristics"][0]["value"], '4"')

    def test_unresolved_links_are_explicit(self):
        with tempfile.TemporaryDirectory() as d:
            cat = write_cat(d, "A.cat", """<catalogue id="a" name="A">
              <entryLinks><entryLink id="x" targetId="missing"/></entryLinks>
            </catalogue>""")
            result = CatalogueResolver([cat]).report(cat)
            self.assertEqual(result["resolverDiagnostics"]["unresolved"], 1)
            self.assertEqual(result["roots"][0]["unresolvedReason"], "targetId not found in supplied catalogues")

    def test_namespace_aware_and_nested_characteristics(self):
        with tempfile.TemporaryDirectory() as d:
            cat = write_cat(d, "N.cat", """<catalogue xmlns="urn:test" id="n" name="Namespaced">
              <selectionEntries><selectionEntry id="e" name="E" type="unit">
                <profiles><profile id="p" name="P" typeName="Ability">
                  <characteristics><characteristic name="Effect">Do this <characteristic name="Nested">first</characteristic> now</characteristic></characteristics>
                </profile></profiles>
              </selectionEntry></selectionEntries>
            </catalogue>""")
            report = CatalogueResolver([cat]).report(cat)
            profile = report["roots"][0]["profiles"][0]
            self.assertIn("first", profile["characteristics"][0]["value"])
            self.assertEqual(profile["characteristics"][0]["name"], "Effect")


if __name__ == "__main__":
    unittest.main()
