import os
import xml.etree.ElementTree as ET
from unittest import mock

from ogre.commands import (
    clear_plugin_parser_cache,
    load_plugin_parser,
)

from . import PLUGIN_FOLDER
from .hardening_helpers import TempFolderTestCase


class TestCommandsHardening(TempFolderTestCase):
    def setUp(self):
        super().setUp()
        clear_plugin_parser_cache()

    def tearDown(self):
        clear_plugin_parser_cache()
        super().tearDown()

    def test_load_plugin_parser_caches_xml_parse_result(self):
        plugin_file = os.path.join(PLUGIN_FOLDER, "void.xml")

        with mock.patch("ogre.commands.ET.parse", wraps=ET.parse) as parse:
            self.assertEqual(load_plugin_parser(plugin_file), ("Void", False))
            self.assertEqual(load_plugin_parser(plugin_file), ("Void", False))

        parse.assert_called_once_with(plugin_file)

    def test_load_plugin_parser_detects_batch_attribute(self):
        plugin_file = os.path.join(PLUGIN_FOLDER, "batched_void.xml")

        self.assertEqual(load_plugin_parser(plugin_file), ("Void", True))
