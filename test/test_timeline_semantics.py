import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from ogre.timeline import build_timeline


class TestTimelineSemantics(TestCase):
    def test_real_database_preserves_values_duplicates_and_timestamp_order(self):
        columns = [
            "timestamp",
            "timestamp_meaning",
            "data_type",
            "related_user",
            "description",
            "additional_description",
        ]
        # Deliberately span files and input order. All timestamps share UTC and
        # precision, as the parser-generated timeline records do.
        early = {
            "timestamp": "2024-01-02T03:04:05.000001Z",
            "timestamp_meaning": "created",
            "data_type": "test:file",
            "related_user": "DOMAIN\\alice",
            "description": 'C:\\Users\\alice\\résumé, "final".txt',
            "additional_description": "first line\nsecond line",
        }
        middle = {
            "timestamp": "2024-01-02T03:04:05.000002Z",
            "timestamp_meaning": "modified",
            "data_type": "test:file",
            "related_user": "",
            "description": "日本語.txt",
            "additional_description": "",
        }
        late = {
            "timestamp": "2024-02-03T00:00:00.000000Z",
            "timestamp_meaning": "deleted",
            "data_type": "test:recycle_bin",
            "related_user": "S-1-5-21-123-456-789-1001",
            "description": "a,b",
            "additional_description": 'literal "quotes" and \\slashes',
        }
        expected = [early, early, middle, late]

        with TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = root / "inputs"
            inputs.mkdir()
            for filename, rows in (
                ("host.first.jsonl", [late, early]),
                ("host.second.jsonl", [middle, early]),
            ):
                with (inputs / filename).open("w", encoding="utf-8") as stream:
                    for row in rows:
                        stream.write(json.dumps(row, ensure_ascii=False) + "\n")

            output = root / "timeline.csv"
            database = root / "database"
            # Rebuilding in the same database/output must replace previous rows.
            for run in range(2):
                with self.subTest(run=run):
                    build_timeline(str(inputs), str(output), str(database))
                    with output.open(encoding="utf-8", newline="") as stream:
                        reader = csv.DictReader(stream)
                        self.assertEqual(reader.fieldnames, columns)
                        self.assertEqual(list(reader), expected)
