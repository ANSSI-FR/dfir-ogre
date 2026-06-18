from unittest import TestCase

from ogre.configuration import Mapping
from ogre.orc_mapping import (
    build_original_lookup,
    compile_mapping_pattern,
    partition_mappings,
)


class TestOrcMapping(TestCase):
    def _mapping(
        self,
        archive_pattern=None,
        original_pattern=None,
        label="label",
        skip_short_name=True,
    ):
        return Mapping(
            archive_pattern,
            original_pattern,
            "plugin.xml",
            label,
            skip_short_name,
            True,
            10,
            {},
            [],
        )

    def test_partition_mappings_splits_archive_and_original_patterns(self):
        archive_mapping = self._mapping(archive_pattern=".*txt")
        original_mapping = self._mapping(original_pattern=".*evtx")

        archive_mappings, original_mappings = partition_mappings(
            [archive_mapping, original_mapping]
        )

        self.assertEqual(archive_mappings, [archive_mapping])
        self.assertEqual(original_mappings, [original_mapping])

    def test_compile_mapping_pattern_reports_label_and_pattern(self):
        mapping = self._mapping(archive_pattern="\\Lite", label="broken")

        with self.assertRaises(Exception) as context:
            compile_mapping_pattern(mapping, "archive_file_pattern")

        message = str(context.exception)
        self.assertIn("archive_file_pattern", message)
        self.assertIn("\\Lite", message)
        self.assertIn("broken", message)

    def test_build_original_lookup_prefers_non_short_name(self):
        from ogre.orc_mapping import OriginalNameMapping

        short = OriginalNameMapping(
            "Event.7z",
            "sample.evtx",
            "\\\\WINDOWS\\\\SVA592~1.PF",
            None,
            None,
            "vss",
        )
        long = OriginalNameMapping(
            "Event.7z",
            "sample.evtx",
            "\\\\Windows\\\\Prefetch\\\\sample.evtx",
            None,
            None,
            "vss",
        )

        result = build_original_lookup([short, long])

        self.assertEqual(result["sample.evtx"], long)
