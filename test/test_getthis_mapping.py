import csv
from pathlib import Path

import py7zr

from ogre.configuration import Mapping
from ogre.folder_input import scan_folder
from ogre.orc_unpacker import unpack_dfir_orc

from .hardening_helpers import TempFolderTestCase


def write_getthis(path, rows, *, bom=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig" if bom else "utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            ["SampleName", "FullName", "CreationDate", "LastModificationDate", "SnapshotID"]
        )
        writer.writerows(rows)


def original_mapping(pattern=r".*\.wer$", *, skip_short_name=True):
    return Mapping(None, pattern, "unused.xml", "original", skip_short_name, False, 10, {}, [])


def archive_mapping():
    return Mapping(r".*\.data$", None, "unused.xml", "archive", True, False, 10, {}, [])


class TestGetThisArchiveMapping(TempFolderTestCase):
    def _inner(self, name, collections):
        root = Path(self.temp_folder)
        archive = root / name
        sample = root / "sample.data"
        sample.write_bytes(b"evidence")
        with py7zr.SevenZipFile(archive, "w") as output:
            for prefix, original in collections:
                csv_file = root / "input.csv"
                write_getthis(csv_file, [[r"WER\sample.data", original, "", "", prefix]], bom=bool(prefix))
                output.write(csv_file, f"{prefix}/getthis.CSV" if prefix else "GetThis.csv")
                output.write(sample, f"{prefix}/WER/sample.data" if prefix else "WER/sample.data")
        return archive

    def _unpack(self, archives):
        root = Path(self.temp_folder)
        main = root / "main.7z"
        with py7zr.SevenZipFile(main, "w") as output:
            for archive in archives:
                output.write(archive, archive.name)
        return unpack_dfir_orc(
            str(main), None, None, [archive_mapping(), original_mapping()], str(root / "unpack")
        )

    def test_nested_indices_resolve_samples_relative_to_each_csv(self):
        originals = {"a": r"C:\a\Report.wer", "b": r"C:\b\Report.wer"}
        result = self._unpack([self._inner("inner.7z", list(originals.items()))])

        self.assertEqual(result.errors, [])
        self.assertEqual(len(result.valid_mapping), 4)
        for entry in result.valid_mapping:
            prefix = entry.archive_file.split("/")[0]
            self.assertEqual(entry.original_file, originals[prefix])
            self.assertEqual(entry.vss, prefix)
            self.assertEqual(entry.relative_path, f"inner/{prefix}/WER")
            self.assertEqual(Path(entry.file).read_bytes(), b"evidence")

    def test_archive_metadata_is_bound_to_the_same_inner_archive(self):
        archives = [
            self._inner("first.7z", [("", r"C:\first\Report.wer")]),
            self._inner("second.7z", [("", r"C:\second\Report.wer")]),
        ]
        result = self._unpack(archives)

        self.assertEqual(result.errors, [])
        self.assertEqual(len(result.valid_mapping), 4)
        for entry in result.valid_mapping:
            self.assertEqual(entry.original_file, rf"C:\{Path(entry.file).parent.parent.name}\Report.wer")

    def test_traversal_index_member_cannot_escape_extraction_directory(self):
        root = Path(self.temp_folder)
        inner = root / "inner.7z"
        escaped = root / "unpack" / "main" / "GetThis.csv"
        with py7zr.SevenZipFile(inner, "w") as output:
            output._writestr(b"SampleName,FullName\n", "../GetThis.csv")

        result = self._unpack([inner])

        self.assertFalse(escaped.exists())
        self.assertTrue(any("Unsafe archive member path" in error for error in result.errors), result.errors)


class TestGetThisFolderMapping(TempFolderTestCase):
    def _root(self):
        root = (Path(self.temp_folder) / "host").resolve()
        root.mkdir()
        return root

    def test_indices_scope_same_named_samples_and_keep_metadata_without_duplicates(self):
        root = self._root()
        for prefix in ("first", "second"):
            sample = root / prefix / "WER" / "sample.data"
            sample.parent.mkdir(parents=True)
            sample.write_bytes(prefix.encode())
            row = [r"WER\sample.data", rf"C:\{prefix}\Report.wer", "2026-01-01T00:00:00Z", "", prefix]
            write_getthis(root / prefix / "getthis.CSV", [row, row], bom=True)

        result = scan_folder(root, [archive_mapping(), original_mapping()], [])

        self.assertEqual(result.errors, [])
        self.assertEqual(len(result.valid_mapping), 4)
        for entry in result.valid_mapping:
            prefix = entry.archive_file.split("/")[0]
            self.assertEqual(entry.original_file, rf"C:\{prefix}\Report.wer")
            self.assertEqual(entry.original_creation_date, "2026-01-01T00:00:00Z")
            self.assertEqual(entry.vss, prefix)
            self.assertEqual(entry.relative_path, f"{prefix}/WER")

    def test_short_names_are_skipped_per_mapping_and_not_used_for_archive_metadata(self):
        root = self._root()
        (root / "sample.data").write_bytes(b"evidence")
        write_getthis(root / "GetThis.csv", [
            ["sample.data", r"C:\REPORT~1.WER", "", "", ""],
            ["sample.data", r"C:\Report.wer", "", "", ""],
        ])
        for skip, expected in ((True, 1), (False, 2)):
            with self.subTest(skip_short_name=skip):
                result = scan_folder(root, [original_mapping(skip_short_name=skip)], [])
                self.assertEqual(result.errors, [])
                self.assertEqual(len(result.valid_mapping), expected)
        archived = scan_folder(root, [archive_mapping()], [])
        self.assertEqual(archived.valid_mapping[0].original_file, r"C:\Report.wer")

    def test_without_metadata_original_patterns_do_not_match_physical_paths(self):
        root = self._root()
        (root / "Report.wer").write_bytes(b"evidence")
        result = scan_folder(root, [original_mapping()], [])
        self.assertEqual(result.valid_mapping, [])
        self.assertEqual(result.errors, [])

    def test_invalid_csv_reports_error_and_other_collections_still_match(self):
        root = self._root()
        (root / "GetThis.csv").write_text("not,a,valid,index\n")
        (root / "good" / "sample.data").parent.mkdir()
        (root / "good" / "sample.data").write_bytes(b"evidence")
        write_getthis(root / "good" / "GetThis.csv", [["sample.data", r"C:\Report.wer", "", "", ""]])

        result = scan_folder(root, [original_mapping()], [])

        self.assertEqual(len(result.valid_mapping), 1)
        self.assertTrue(any("GetThis.csv" in error for error in result.errors), result.errors)

    def test_missing_unsafe_symlinked_and_excluded_samples_are_never_selected(self):
        root = self._root()
        outside = root.parent / "outside.data"
        outside.write_bytes(b"outside")
        (root / "link.data").symlink_to(outside)
        (root / "excluded.data").write_bytes(b"excluded")
        cases = ["../outside.data", str(outside), r"C:\outside.data", "link.data", "missing.data", "excluded.data"]
        for name in cases:
            with self.subTest(sample=name):
                write_getthis(root / "GetThis.csv", [[name, r"C:\Report.wer", "", "", ""]])
                result = scan_folder(root, [original_mapping()], [root / "excluded.data"])
                self.assertEqual(result.valid_mapping, [])
                self.assertTrue(result.errors)

    def test_conflicting_indices_do_not_assign_an_arbitrary_original_path(self):
        root = self._root()
        (root / "nested").mkdir()
        (root / "nested" / "sample.data").write_bytes(b"evidence")
        write_getthis(root / "GetThis.csv", [["nested/sample.data", r"C:\first\Report.wer", "", "", ""]])
        write_getthis(root / "nested" / "GetThis.csv", [["sample.data", r"C:\second\Report.wer", "", "", ""]])

        result = scan_folder(root, [original_mapping()], [])

        self.assertEqual(result.valid_mapping, [])
        self.assertTrue(any("Ambiguous" in error for error in result.errors), result.errors)
