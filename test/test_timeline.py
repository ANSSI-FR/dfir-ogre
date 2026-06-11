import os
from unittest import TestCase

from ogre import cli

from . import TEMP_FOLDER


class TestMain(TestCase):
    # python -m unittest test.test_timeline.TestMain.test_timeline_run -v
    def test_timeline_run(self):
        archive = os.path.join(
            "test", "data", "archive", "ORC_WorkStation_WXPSP2_20250325_133230_Outcome.json"
        )
        output_folder = os.path.join(TEMP_FOLDER, "timeline")
        configuration = os.path.join("test", "data", "ogre_timeline.yaml")

        from argparse import Namespace

        args = Namespace(
            archive=archive,
            timeline_folder=output_folder,
            configuration=configuration,
            password="",
            case="",
        )
        cli.handle_timeline(args)

        with open(".tmp/timeline/WXPSP2.timeline.csv") as file:
            line_count = sum(1 for line in file)

        self.assertEqual(line_count, 183963)
