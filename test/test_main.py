import glob
import json
import os
import shutil
import sys
from unittest import TestCase, mock

from ogre import main

from . import TEMP_FOLDER


class TestMain(TestCase):
    def test_main_run(self):
        from .sample_plugin import SampleTexLine  # noqa: F401

        shutil.rmtree(os.path.join(".tmp", "main"), ignore_errors=True)
        conf_file = os.path.join("test", "data", "test_main.yaml")
        archive = os.path.join("test", "data", "archive", "secret.7z")
        with mock.patch(
            "sys.argv",
            [
                "dfir-ogre",
                "orc",
                "--archive",
                archive,
                "--configuration",
                conf_file,
                "--password",
                "password",
            ],
        ):
            stdout_file = os.path.join(TEMP_FOLDER, "stdout.txt")
            with open(stdout_file, "w") as file:
                original_stdout = sys.stdout
                sys.stdout = file
                try:
                    main()
                finally:
                    sys.stdout = original_stdout

        os.remove(stdout_file)
        output_file = os.path.join(
            ".tmp", "main", "output", "secret", "text_output", "hello.test.jsonl"
        )
        data = ""
        with open(output_file) as f:
            data = json.load(f)
            self.assertEqual(data["line"], "Hello world!")
            self.assertEqual(data["ogre_md"]["archive"], "secret.7z")
            self.assertEqual(data["ogre_md"]["archive_filename"], "hello.txt")
            self.assertEqual(data["ogre_md"]["computer"], "secret")

        report_output = os.path.join(".tmp", "main", "output", "report_secret_*")
        files = glob.glob(report_output, recursive=False)

        with open(files[0]) as f:
            report = json.load(f)
            self.assertEqual(report["run_results"][0]["parser"], "SampleText")

        shutil.rmtree(os.path.join(".tmp", "main"))
