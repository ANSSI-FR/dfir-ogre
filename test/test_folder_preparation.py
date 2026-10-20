from datetime import datetime, timezone
from pathlib import Path
from unittest import mock
from uuid import UUID

import yaml

from ogre.dfir_orc_unpack import FileMapping, UnpackResult
from ogre.run_preparation import (
    ArchiveRunPlanner,
    PluginDefinition,
    VariableResolver,
)

from .hardening_helpers import TempFolderTestCase
from .test_run_preparation import _configuration, _mapping, _outcome, _output


class TestFolderPreparation(TempFolderTestCase):
    def _root(self) -> Path:
        root = (Path(self.temp_folder) / "host.v2").resolve()
        (root / "logs").mkdir(parents=True)
        (root / "logs" / "a.txt").write_text("evidence")
        return root

    def _write_config(self, root: Path, mappings=None) -> str:
        if mappings is None:
            mappings = [
                {
                    "archive_file_pattern": r".*\.txt$",
                    "plugin_file": "$plugin_folder/void.xml",
                    "mapping_label": "first",
                    "output": ["raw"],
                    "source": "$archive_name",
                }
            ]
        config = {
            "plugin_prefixes": ["test"],
            "case": "test",
            "output_folder": str(root.parent / "out"),
            "report_folder": str(root.parent / "reports"),
            "temp_folder": str(root.parent / "tmp"),
            "plugin_folder": "test/plugin_config",
            "mapping": mappings,
            "output": {
                "raw": {
                    "type": "file",
                    "format": "jsonl",
                    "date_format": "iso",
                    "output_folder": "$output_folder/$archive_name/$relative_path",
                    "base_file_name": "$relative_path/$file_name",
                }
            },
        }
        path = Path(self.temp_folder) / "config.yaml"
        path.write_text(yaml.safe_dump(config))
        return str(path)

    def test_folder_preparation_uses_source_file_and_folder_metadata(self):
        from ogre.run_preparation import prepare_folder_runs

        root = self._root()
        config_path = self._write_config(root)
        result = prepare_folder_runs(
            config_path,
            str(root),
            None,
            started_at=datetime(2025, 9, 4, 22, 11, 44, tzinfo=timezone.utc),
        )

        self.assertEqual(result.errors, [])
        self.assertEqual(result.source_folder, str(root))
        self.assertEqual(result.computer, "host.v2")
        self.assertIsNone(result.archive)
        self.assertIsNone(result.orc_id)
        UUID(result.run_id)
        entries = next(iter(result.runs.map.values())).batch_entries
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry.file, str(root / "logs" / "a.txt"))
        self.assertEqual(entry.metadata.computer, "host.v2")
        self.assertEqual(entry.metadata.folder, "host.v2")
        self.assertEqual(entry.metadata.archive_filename, "logs/a.txt")
        self.assertIsNone(entry.metadata.archive)
        self.assertIsNone(entry.metadata.subarchive)
        self.assertIsNone(entry.metadata.orc_id)
        self.assertEqual(entry.run_config.params["source"], "host.v2")
        self.assertEqual(entry.run_config.output[0].base_file_name, "logs_a")
        self.assertEqual(
            entry.run_config.output[0].output_folder,
            str(root.parent / "out" / "host.v2" / "logs"),
        )

    def test_explicit_computer_and_two_mappings_produce_two_distinct_outputs(self):
        from ogre.run_preparation import prepare_folder_runs

        root = self._root()
        config_path = self._write_config(
            root,
            mappings=[
                {
                    "archive_file_pattern": r".*\.txt$",
                    "plugin_file": "$plugin_folder/void.xml",
                    "mapping_label": label,
                    "output": ["raw"],
                }
                for label in ("first", "second")
            ],
        )
        result = prepare_folder_runs(config_path, str(root), "investigator-name")

        entries = next(iter(result.runs.map.values())).batch_entries
        self.assertEqual(len(entries), 2)
        self.assertEqual([entry.metadata.computer for entry in entries], ["investigator-name"] * 2)
        self.assertEqual([entry.metadata.folder for entry in entries], ["host.v2"] * 2)
        self.assertNotEqual(
            entries[0].run_config.output[0].base_file_name,
            entries[1].run_config.output[0].base_file_name,
        )

    def test_output_basename_cannot_redirect_writes_into_source_files(self):
        from ogre.run_preparation import prepare_folder_runs

        root = self._root()
        config_path = self._write_config(root)
        config = yaml.safe_load(Path(config_path).read_text())
        for output_folder, basename in (
            (root.parent / "out", "../host.v2/logs/a"),
            (root.parent / "out", str(root / "logs" / "a")),
            (root / "generated", "../logs/a"),
        ):
            with self.subTest(output_folder=output_folder, basename=basename):
                config["output"]["raw"]["output_folder"] = str(output_folder)
                config["output"]["raw"]["base_file_name"] = basename
                Path(config_path).write_text(yaml.safe_dump(config))

                with self.assertRaises(ValueError):
                    prepare_folder_runs(config_path, str(root), None)

        self.assertEqual((root / "logs" / "a.txt").read_text(), "evidence")

    def test_output_basename_keeps_safe_nested_destinations(self):
        from ogre.run_preparation import prepare_folder_runs

        root = self._root()
        config_path = self._write_config(root)
        config = yaml.safe_load(Path(config_path).read_text())
        for output_folder in (root.parent / "out", root / "generated"):
            with self.subTest(output_folder=output_folder):
                config["output"]["raw"]["output_folder"] = str(output_folder)
                config["output"]["raw"]["base_file_name"] = "nested/a"
                Path(config_path).write_text(yaml.safe_dump(config))

                result = prepare_folder_runs(config_path, str(root), None)

                entry = next(iter(result.runs.map.values())).batch_entries[0]
                self.assertEqual(entry.run_config.output[0].base_file_name, "nested/a")

    def test_original_only_mappings_without_metadata_do_not_load_xml_or_unpack_archives(self):
        from ogre.run_preparation import prepare_folder_runs

        root = self._root()
        config_path = self._write_config(
            root,
            mappings=[
                {
                    "original_file_pattern": r".*\.txt$",
                    "plugin_file": "missing-original-only.xml",
                    "mapping_label": "original",
                    "output": ["raw"],
                }
            ],
        )
        with mock.patch(
            "ogre.run_preparation.ArchiveRunPlanner.plan",
            side_effect=AssertionError("7z planner called"),
        ):
            result = prepare_folder_runs(config_path, str(root), None)

        self.assertEqual(result.runs.map, {})
        self.assertTrue(any("No files matched" in error for error in result.errors))

    def test_folder_original_patterns_are_validated(self):
        from ogre.run_preparation import prepare_folder_runs

        root = self._root()
        config_path = self._write_config(root, mappings=[{
            "original_file_pattern": "[",
            "plugin_file": "missing.xml",
            "mapping_label": "original",
            "output": ["raw"],
        }])
        with self.assertRaisesRegex(Exception, "original_file_pattern"):
            prepare_folder_runs(config_path, str(root), None)

    def test_original_mapping_uses_getthis_metadata_and_reserves_its_output(self):
        from ogre.run_preparation import prepare_folder_runs
        from .test_getthis_mapping import write_getthis

        root = self._root()
        write_getthis(root / "GetThis.csv", [[
            r"logs\a.txt", r"C:\Windows\Report.wer", "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", "snapshot",
        ]])
        config_path = self._write_config(root, mappings=[{
            "original_file_pattern": r".*\\Report\.wer$",
            "plugin_file": "$plugin_folder/void.xml",
            "mapping_label": "wer",
            "output": ["raw"],
        }])
        config = yaml.safe_load(Path(config_path).read_text())
        config["output"]["raw"]["output_folder"] = str(root / "generated" / "$mapping_label")
        Path(config_path).write_text(yaml.safe_dump(config))

        result = prepare_folder_runs(config_path, str(root), None)

        self.assertEqual(result.errors, [])
        entry = next(iter(result.runs.map.values())).batch_entries[0]
        self.assertEqual(entry.file, str(root / "logs" / "a.txt"))
        self.assertEqual(entry.metadata.original_filename, r"C:\Windows\Report.wer")
        self.assertEqual(entry.metadata.vss, "snapshot")
        self.assertEqual(entry.metadata.creation_date, datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(entry.metadata.modif_date, datetime(2026, 1, 2, tzinfo=timezone.utc))
        self.assertEqual(entry.run_config.output[0].output_folder, str(root / "generated" / "wer"))

    def test_orc_collision_suffix_is_independent_of_extraction_uuid(self):
        mapping = _mapping(output=["rawjson"])
        outcome = _outcome(archives=["main.7z"])

        def planned_names(temp_uuid):
            config = _configuration(
                mapping=[mapping],
                temp_folder=str(Path(self.temp_folder) / temp_uuid),
                output={
                    "rawjson": _output(
                        output_folder="out",
                        base_file_name="$relative_path/$file_name",
                    )
                },
            )
            resolver = VariableResolver(config, outcome)

            def fake_unpack(*_args):
                return UnpackResult(
                    [
                        FileMapping(
                            file=str(Path(config.temp_folder) / suffix / "file.txt"),
                            archive_name="",
                            archive_file=member,
                            original_file=None,
                            original_creation_date=None,
                            original_modification_date=None,
                            mapping=mapping,
                            vss=None,
                            error=None,
                            relative_path=parent,
                        )
                        for suffix, member, parent in (
                            ("first", "a/b_c/file.txt", "a/b_c"),
                            ("second", "a/b/c/file.txt", "a/b/c"),
                        )
                    ],
                    [],
                )

            planner = ArchiveRunPlanner(
                config,
                outcome,
                None,
                {"Void": PluginDefinition("Void", "ogre.void_parser", False)},
                resolver,
                unpack=fake_unpack,
                load_parser=lambda _path: ("Void", False),
            )
            runs = planner.plan().runs
            entries = next(iter(runs.map.values())).batch_entries
            return {
                entry.metadata.archive_filename: entry.run_config.output[0].base_file_name
                for entry in entries
            }

        first = planned_names("uuid-one")
        second = planned_names("uuid-two")
        self.assertEqual(first, second)
        self.assertNotEqual(first["a/b_c/file.txt"], first["a/b/c/file.txt"])
