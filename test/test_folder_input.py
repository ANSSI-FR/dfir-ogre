import os
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import yaml
from dfir_ogre_common import BatchEntry, Metadata, RunConfiguration

from ogre.configuration import Mapping
from ogre.run_preparation import RunConfigGrouper, RunVariables, VariableResolver

from .hardening_helpers import TempFolderTestCase
from .test_run_preparation import _configuration, _output


def _mapping(label: str, pattern: str) -> Mapping:
    return Mapping(pattern, None, "unused.xml", label, True, False, 10, {}, [])


class TestFolderScan(TempFolderTestCase):
    def test_root_and_nested_regexes_match_relative_paths_in_file_order(self):
        from ogre.folder_input import scan_folder

        root = (Path(self.temp_folder) / "host").resolve()
        (root / "logs").mkdir(parents=True)
        (root / "a.evtx").write_text("a")
        (root / "logs" / "b.EVTX").write_text("b")
        outside = Path(self.temp_folder) / "outside.evtx"
        outside.write_text("outside")
        (root / "link.evtx").symlink_to(outside)
        (root / "linked_logs").symlink_to(root / "logs", target_is_directory=True)

        result = scan_folder(
            root,
            [
                _mapping("root", r"^a\.evtx$"),
                _mapping("nested", r"^logs/.*\.evtx$"),
                _mapping("both", r".*\.evtx$"),
            ],
            [],
        )

        self.assertEqual(result.errors, [])
        self.assertEqual(
            [(entry.archive_file, entry.mapping.mapping_label) for entry in result.valid_mapping],
            [
                ("a.evtx", "root"),
                ("a.evtx", "both"),
                ("logs/b.EVTX", "nested"),
                ("logs/b.EVTX", "both"),
            ],
        )
        self.assertEqual(
            [entry.relative_path for entry in result.valid_mapping],
            ["", "", "logs", "logs"],
        )
        self.assertTrue(all(Path(entry.file).is_file() for entry in result.valid_mapping))

    def test_child_scan_error_keeps_readable_sibling_matches(self):
        from ogre.folder_input import scan_folder

        root = (Path(self.temp_folder) / "host").resolve()
        readable = root / "readable"
        blocked = root / "blocked"
        readable.mkdir(parents=True)
        blocked.mkdir()
        (readable / "a.evtx").write_text("a")
        original_scandir = os.scandir

        def fail_blocked(path):
            if Path(path) == blocked:
                raise PermissionError("blocked child")
            return original_scandir(path)

        with mock.patch("ogre.folder_input.os.scandir", side_effect=fail_blocked):
            result = scan_folder(root, [_mapping("all", r".*\.evtx$")], [])

        self.assertEqual(
            [entry.archive_file for entry in result.valid_mapping],
            ["readable/a.evtx"],
        )
        self.assertEqual(len(result.errors), 1)
        self.assertIn("blocked child", result.errors[0])


class TestFolderPathPolicy(TempFolderTestCase):
    def _root(self) -> Path:
        root = (Path(self.temp_folder) / "host").resolve()
        root.mkdir()
        return root

    def _config(self, root: Path, **overrides):
        values = {
            "output_folder": str(root.parent / "out"),
            "report_folder": str(root.parent / "reports"),
            "temp_folder": str(root.parent / "tmp" / "uuid"),
            "output": {"rawjson": _output(output_folder="$output_folder/$relative_path")},
        }
        values.update(overrides)
        return _configuration(**values)

    def _resolver(self, config, root: Path):
        return VariableResolver(
            config,
            RunVariables(root.name, datetime(2025, 9, 4, tzinfo=timezone.utc), None),
        )

    def _empty_config(self) -> str:
        config_path = Path(self.temp_folder) / "empty.yaml"
        config_path.write_text("{}\n")
        return str(config_path)

    def test_root_must_exist_be_directory_and_be_readable(self):
        from ogre.folder_input import validate_folder_root

        root = self._root()
        ordinary_file = root / "file.evtx"
        ordinary_file.write_text("event")
        self.assertEqual(validate_folder_root(str(root)), root)
        with self.assertRaises((OSError, ValueError)):
            validate_folder_root(str(root / "missing"))
        with self.assertRaises((OSError, ValueError)):
            validate_folder_root(str(ordinary_file))
        with mock.patch("ogre.folder_input.os.scandir", side_effect=PermissionError("no access")):
            with self.assertRaisesRegex((OSError, ValueError), "no access"):
                validate_folder_root(str(root))

    def test_output_report_and_temp_areas_cannot_contain_source_root(self):
        from ogre.folder_input import plan_folder_exclusions

        root = self._root()
        for overrides in (
            {"output_folder": str(root)},
            {"output_folder": str(root.parent)},
            {"report_folder": str(root)},
            {"report_folder": str(root.parent)},
            {"temp_folder": str(root / "uuid")},
        ):
            with self.subTest(overrides=overrides):
                config = self._config(root, **overrides)
                with self.assertRaises(ValueError):
                    plan_folder_exclusions(
                        root, config, self._resolver(config, root), self._empty_config()
                    )

    def test_in_root_destinations_logs_and_backups_are_excluded_from_scan(self):
        from ogre.folder_input import plan_folder_exclusions, scan_folder

        root = self._root()
        (root / "source.evtx").write_text("evidence")
        for destination in (
            root / "generated" / "old.evtx",
            root / "reports" / "old.evtx",
            root / "tmp" / "uuid" / "old.evtx",
            root / "logs" / "ogre.log",
            root / "logs" / "ogre.log.1",
        ):
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text("generated")
        config_path = Path(self.temp_folder) / "logs.yaml"
        config_path.write_text(
            yaml.safe_dump(
                {
                    "log_file_path": str(root / "logs"),
                    "log_file_name": "ogre.log",
                    "log_backup_count": 1,
                }
            )
        )
        config = self._config(
            root,
            output_folder=str(root / "generated"),
            report_folder=str(root / "reports"),
            temp_folder=str(root / "tmp" / "uuid"),
        )

        exclusions = plan_folder_exclusions(
            root, config, self._resolver(config, root), str(config_path)
        )
        result = scan_folder(root, [_mapping("all", r".*")], exclusions)

        self.assertEqual([entry.archive_file for entry in result.valid_mapping], ["source.evtx"])
        self.assertIn((root / "logs" / "ogre.log").resolve(), exclusions)
        self.assertIn((root / "logs" / "ogre.log.1").resolve(), exclusions)

    def test_symlinked_output_destination_is_classified_by_target(self):
        from ogre.folder_input import plan_folder_exclusions

        root = self._root()
        generated = root / "generated"
        generated.mkdir()
        link = root.parent / "output_link"
        link.symlink_to(generated, target_is_directory=True)
        config = self._config(root, output_folder=str(link))

        exclusions = plan_folder_exclusions(
            root, config, self._resolver(config, root), self._empty_config()
        )
        self.assertIn(generated, exclusions)

        link.unlink()
        link.symlink_to(root, target_is_directory=True)
        config = self._config(root, output_folder=str(link))
        with self.assertRaises(ValueError):
            plan_folder_exclusions(root, config, self._resolver(config, root), self._empty_config())

    def test_dynamic_output_under_source_requires_fixed_exclusion_area(self):
        from ogre.folder_input import plan_folder_exclusions

        root = self._root()
        config = self._config(
            root,
            output={"rawjson": _output(output_folder=str(root / "$relative_path"))},
        )
        with self.assertRaises(ValueError):
            plan_folder_exclusions(root, config, self._resolver(config, root), self._empty_config())

    def test_mapping_output_fixed_prefix_uses_known_template_values(self):
        from ogre.folder_input import plan_folder_exclusions, scan_folder

        root = self._root()
        (root / "source.evtx").write_text("evidence")
        old_output = root / "generated" / "text_output" / "host" / "logs" / "old.evtx"
        old_output.parent.mkdir(parents=True)
        old_output.write_text("generated")
        config = self._config(
            root,
            output={
                "rawjson": _output(
                    output_folder=str(
                        root / "generated" / "$mapping_label" / "$computer_name" / "$relative_path"
                    )
                )
            },
        )

        exclusions = plan_folder_exclusions(
            root, config, self._resolver(config, root), self._empty_config()
        )
        result = scan_folder(root, [_mapping("all", r".*")], exclusions)

        self.assertIn(root / "generated" / "text_output" / "host", exclusions)
        self.assertEqual([entry.archive_file for entry in result.valid_mapping], ["source.evtx"])

    def test_concrete_mapped_output_uses_same_overlap_check(self):
        from ogre.folder_input import validate_concrete_folder_outputs

        root = self._root()
        output = _output(output_folder=str(root))
        batch_entry = BatchEntry(
            str(root / "source.evtx"),
            RunConfiguration([output], False, {}),
            Metadata("host"),
        )
        runs = RunConfigGrouper()
        runs.add(batch_entry, "plugin.xml", "all", "plugin.module", "Parser", False, 10)

        with self.assertRaises(ValueError):
            validate_concrete_folder_outputs(root, runs)

        safe_entry = BatchEntry(
            str(root / "source.evtx"),
            RunConfiguration([_output(output_folder=str(root / "generated"))], False, {}),
            Metadata("host"),
        )
        safe_runs = RunConfigGrouper()
        safe_runs.add(safe_entry, "plugin.xml", "all", "plugin.module", "Parser", False, 10)
        validate_concrete_folder_outputs(root, safe_runs)
