from unittest import TestCase

from ogre.cli import (
    build_parser,
    display_plugin_list,
    handle_orc_archive,
    handle_timeline,
    run_plugin,
)


class TestCli(TestCase):
    def test_build_parser_dispatches_list_command(self):
        args = build_parser().parse_args(
            [
                "list",
                "--configuration",
                "ogre.yaml",
            ]
        )

        self.assertIs(args.func, display_plugin_list)
        self.assertEqual(args.configuration, "ogre.yaml")
        self.assertEqual(args.case, "default_case")

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
        self.assertEqual(args.case, "default_case")
        self.assertIsNone(args.password)

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
        self.assertEqual(args.computer_name, "host")
        self.assertEqual(args.output_folder, "out")
        self.assertIsNone(args.output_format)
        self.assertIsNone(args.output_date_format)
        self.assertIsNone(args.params)
        self.assertFalse(args.timeline)
        self.assertFalse(args.include_empty)
        self.assertIsNone(args.library)

    def test_build_parser_keeps_plugin_optional_flags(self):
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
                "--output_format",
                "csv",
                "--output_date_format",
                "epoch",
                "--params",
                '{"a": 1}',
                "--timeline",
                "--include_empty",
                "--library",
                "custom.parsers",
            ]
        )

        self.assertEqual(args.output_format, "csv")
        self.assertEqual(args.output_date_format, "epoch")
        self.assertEqual(args.params, '{"a": 1}')
        self.assertTrue(args.timeline)
        self.assertTrue(args.include_empty)
        self.assertEqual(args.library, "custom.parsers")

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
        self.assertEqual(args.archive, "archive.7z")
        self.assertEqual(args.configuration, "ogre.yaml")
        self.assertEqual(args.case, "default_case")
        self.assertIsNone(args.password)
