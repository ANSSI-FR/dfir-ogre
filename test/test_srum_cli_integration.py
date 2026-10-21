"""Opt-in regression for the installed ``dfir-ogre`` console entry point.

Install non-editable dfir-ogre, dfir-ogre-common and dfir-ogre-plugin-windows
wheels into the Python environment, and keep the Windows plugin checkout beside
this repository for its configuration and real SRUM fixture. From this repository:

    DFIR_OGRE_RUN_SRUM_INTEGRATION=1 python -m unittest test.test_srum_cli_integration -v

Default discovery skips this cross-repository test. Opting in makes missing
fixtures, missing packages and editable/source imports test failures.
"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless


WINDOWS_PLUGIN = Path(__file__).resolve().parents[2] / "dfir-ogre-plugin-windows"
EXPECTED_COUNTS = {
    "srum_app_timeline": 1660,
    "srum_application_resources": 562,
    "srum_energy_estimation": 0,
    "srum_energy_usage": 0,
    "srum_energy_usage_long_term": 0,
    "srum_network_connectivity_usage": 6,
    "srum_network_data_usage": 96,
    "srum_sdp_cpu": 0,
    "srum_sdp_network": 0,
    "srum_sdp_physical_disk": 0,
    "srum_sdp_volume": 0,
    "srum_tagged_energy": 0,
    "srum_vfuprov": 26,
    "srum_wpn_provider": 5,
}

# Resolve the installed console entry point with the same Python running the
# test. Isolated mode and a temporary cwd exclude PYTHONPATH and checkout imports;
# the origin check also rejects editable installations supplied by import hooks.
INSTALLED_CLI = """
import importlib
import importlib.metadata
import sys
from pathlib import Path

for distribution_name, module_name in (
    ('dfir-ogre', 'ogre'),
    ('dfir-ogre-common', 'dfir_ogre_common'),
    ('dfir-ogre-plugin-windows', 'dfir_ogre_plugin_windows'),
):
    distribution = importlib.metadata.distribution(distribution_name)
    module = importlib.import_module(module_name)
    root = Path(distribution.locate_file('')).resolve()
    origin = Path(module.__file__).resolve()
    if not origin.is_relative_to(root):
        raise RuntimeError(f'{distribution_name} must be installed non-editably: {origin}')

common = importlib.import_module('dfir_ogre_common')
if hasattr(common, 'parse_srum'):
    raise RuntimeError('Install the migrated common wheel without the Rust SRUM API')

entry_point = next(
    entry for entry in importlib.metadata.distribution('dfir-ogre').entry_points
    if entry.group == 'console_scripts' and entry.name == 'dfir-ogre'
)
sys.argv[0] = 'dfir-ogre'
raise SystemExit(entry_point.load()())
"""


@skipUnless(
    os.environ.get("DFIR_OGRE_RUN_SRUM_INTEGRATION") == "1",
    "set DFIR_OGRE_RUN_SRUM_INTEGRATION=1 to test installed wheels with the SRUM fixture",
)
class TestInstalledSrumCli(TestCase):
    def test_installed_cli_parses_real_srum_database(self):
        database = WINDOWS_PLUGIN / "tests" / "data" / "srum" / "SRUDB.dat"
        configuration = WINDOWS_PLUGIN / "configuration" / "srum.xml"
        self.assertTrue(database.is_file(), f"Missing sibling SRUM fixture: {database}")
        self.assertTrue(
            configuration.is_file(), f"Missing SRUM configuration: {configuration}"
        )
        self.assertEqual(
            hashlib.sha256(database.read_bytes()).hexdigest(),
            "fb3b913c8a94fae7d73f6d5641af9dd1a0040133744e07927082214a436d5c00",
        )

        with TemporaryDirectory() as folder:
            result = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-c",
                    INSTALLED_CLI,
                    "plugin",
                    "--plugin_config",
                    str(configuration),
                    "--computer_name",
                    "srum-install-check",
                    "--output_folder",
                    folder,
                    "--output_format",
                    "jsonl",
                    "--filename",
                    str(database),
                    "--timeout",
                    "30",
                ],
                cwd=folder,
                capture_output=True,
                text=True,
                timeout=60,
            )
            logs = f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            self.assertEqual(result.returncode, 0, logs)
            # Plugin worker errors can leave the supervising CLI exit code at 0.
            self.assertNotRegex(logs, r" - (?:ERROR|CRITICAL) - |Traceback \(", logs)
            self.assertEqual(
                {path.name for path in Path(folder).iterdir()},
                {f"SRUDB.{provider}.jsonl" for provider in EXPECTED_COUNTS},
                logs,
            )
            records = {
                provider: [
                    json.loads(line)
                    for line in Path(folder, f"SRUDB.{provider}.jsonl")
                    .read_text(encoding="utf-8")
                    .splitlines()
                ]
                for provider in EXPECTED_COUNTS
            }

        self.assertEqual(
            {provider: len(rows) for provider, rows in records.items()},
            EXPECTED_COUNTS,
        )
        timeline = next(
            row for row in records["srum_app_timeline"] if row["incremental_id"] == 94
        )
        self.assertEqual(timeline["timestamp"], "2022-03-10T16:34:59.999999+00:00")
        self.assertEqual(timeline["app_id"], "!!spoolsv.exe!2015/05/01:18:16:33!d7253!")
        self.assertEqual(timeline["user_id"], "S-1-5-18")
        self.assertEqual(timeline["cycles"], 13655040210)
        self.assertEqual(
            timeline["ogre_md"],
            {
                "computer": "srum-install-check",
                "data_type": "srum_app_timeline",
                "archive_filename": str(database),
            },
        )
        network = next(
            row
            for row in records["srum_network_data_usage"]
            if row["incremental_id"] == 1
        )
        self.assertEqual(network["bytes_sent"], 1721816)
        self.assertEqual(network["bytes_recvd"], 131866573)
