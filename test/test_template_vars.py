from unittest import TestCase

from ogre.template_vars import apply_dir_tree, replace_placeholders


class TestTemplateVars(TestCase):
    def test_replace_placeholders(self):
        result = replace_placeholders(
            "$output_folder/$archive_name/$case/$timestamp",
            {
                "output_folder": "out",
                "archive_name": "archive",
                "case": "case",
                "timestamp": "20250102_030405",
            },
        )

        self.assertEqual(result, "out/archive/case/20250102_030405")

    def test_apply_dir_tree_preserves_legacy_fallback(self):
        self.assertEqual(
            apply_dir_tree("/data/$dir_tree/report", "presta/SuperIR", ""),
            "/data/presta/SuperIR/report",
        )
        self.assertEqual(
            apply_dir_tree("/data/$dir_tree/report", None, ""),
            "/data/report",
        )
