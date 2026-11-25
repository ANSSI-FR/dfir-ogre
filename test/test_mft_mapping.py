"""Default mapping for raw MFT samples collected by GetThis."""

import csv
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from unittest import TestCase

import yaml

from ogre.configuration import load_mapping
from ogre.folder_input import scan_folder


class MftMappingTest(TestCase):
    def mappings(self):
        config = Path(__file__).resolve().parents[1] / "configuration" / "ogre.yaml"
        return [
            load_mapping(dict(item), 3600, False)
            for item in yaml.safe_load(config.read_text())["mapping"]
            if item.get("mapping_label") == "mft"
        ]

    def test_collected_mft_uses_the_mft_plugin_and_both_outputs(self):
        mappings = self.mappings()
        self.assertEqual(len(mappings), 1)
        mapping = mappings[0]
        self.assertTrue(mapping.plugin_file.endswith("/mft.xml"))
        self.assertEqual(mapping.output, ["timeline", "raw_data"])
        pattern = re.compile(mapping.original_file_pattern, re.IGNORECASE)
        self.assertIsNotNone(pattern.match(r"C:\$MFT"))
        for name in (r"C:\$MFTMirr", r"C:\$UsnJrnl", r"C:\MFT.csv"):
            self.assertIsNone(pattern.match(name))

    def test_getthis_resolves_a_renamed_raw_mft_once(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "sample.data").write_bytes(b"MFT fixture placeholder")
            with (root / "GetThis.csv").open("w", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(
                    [
                        "SampleName",
                        "FullName",
                        "CreationDate",
                        "LastModificationDate",
                        "SnapshotID",
                    ]
                )
                writer.writerow(["sample.data", r"C:\$MFT", "", "", ""])
            result = scan_folder(root, self.mappings(), [])
            self.assertEqual(result.errors, [])
            self.assertEqual(len(result.valid_mapping), 1)
            self.assertEqual(result.valid_mapping[0].original_file, r"C:\$MFT")
