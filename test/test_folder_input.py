import os
from pathlib import Path
from unittest import mock

from ogre.configuration import Mapping

from .hardening_helpers import TempFolderTestCase


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
