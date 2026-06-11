from unittest import TestCase

from ogre.cli import build_parser, handle_orc_archive, handle_timeline, run_plugin


class TestCli(TestCase):
    def test_build_parser_dispatches_orc_command(self):
        args = build_parser().parse_args(
            [
                "orc",
                "--archive",
                "archive.7z",
                "--configuration",
                "ogre.yaml",
            ]
        )

        self.assertIs(args.func, handle_orc_archive)
        self.assertEqual(args.archive, "archive.7z")
        self.assertEqual(args.configuration, "ogre.yaml")

    def test_build_parser_dispatches_plugin_command(self):
        args = build_parser().parse_args(
            [
                "plugin",
                "--filename",
                "input.txt",
                "--plugin_config",
                "plugin.xml",
                "--computer_name",
                "host",
                "--output_folder",
                "out",
            ]
        )

        self.assertIs(args.func, run_plugin)
        self.assertEqual(args.filename, "input.txt")
        self.assertEqual(args.plugin_config, "plugin.xml")

    def test_build_parser_dispatches_timeline_command(self):
        args = build_parser().parse_args(
            [
                "timeline",
                "--timeline_folder",
                "timeline",
                "--archive",
                "archive.7z",
                "--configuration",
                "ogre.yaml",
            ]
        )

        self.assertIs(args.func, handle_timeline)
        self.assertEqual(args.timeline_folder, "timeline")
