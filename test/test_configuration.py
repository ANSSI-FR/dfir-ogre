import copy
import os
from typing import Any
from unittest import TestCase

import yaml

from ogre.configuration import (
    build_configuration,
    load_mapping,
    load_output_configuration,
)


class TestConfiguration(TestCase):
    def test_conf_from_map(self):
        dict_conf = {
            "plugin_prefixes": ["-ogre-anssi"],
            "case": "test_case",
            "temp_folder": ".tmp",
            "output_folder": ".output",
            "plugin_folder": "$case/conf",
            "mapping": [
                {
                    "archive_file_pattern": "*.txt",
                    "plugin_file": "txt",
                    "mapping_label": "sometext",
                    "config_file": "test.cfg",
                    "output": ["rawjson"],
                }
            ],
            "output": {
                "rawjson": {
                    "type": "file",
                    "format": "json",
                    "date_format": "iso",
                    "with_timeline": False,
                    "output_folder": ".tmp/",
                    "base_file_name": "test",
                }
            },
        }

        conf = build_configuration(copy.deepcopy(dict_conf), {})
        self.assertEqual(dict_conf["plugin_prefixes"], conf.plugin_prefixes)
        self.assertEqual(
            dict_conf["mapping"][0]["archive_file_pattern"],
            conf.mapping[0].archive_file_pattern,
        )
        original = copy.deepcopy(dict_conf)
        _ = build_configuration(dict_conf, {})
        self.assertEqual(original, dict_conf)
        # self.assertEqual(
        #     dict_conf["output"]["rawjson"]["type"], conf.output["rawjson"].type
        # )

    def test_conf_from_yaml(self):
        yaml_conf = """
plugin_prefixes:
- -ogre-anssi
case: testcase
temp_folder: .tmp
output_folder: .tmp
plugin_folder: $case/conf,
mapping:
- archive_file_pattern: '*.txt'
  plugin_file: $plugin_folder/_txt.xml
  config_file: test.cfg
  mapping_label: text_output
  output:
  - rawjson

output:
  rawjson:
    type: file
    format: jsonl
    date_format: iso
    with_timeline: false
    output_folder: .tmp/
    base_file_name: test,
    """
        dict_conf: dict = yaml.safe_load(yaml_conf)
        conf = build_configuration(copy.deepcopy(dict_conf), {})
        self.assertEqual(dict_conf["plugin_prefixes"], conf.plugin_prefixes)
        self.assertEqual(
            dict_conf["mapping"][0]["archive_file_pattern"],
            conf.mapping[0].archive_file_pattern,
        )

    def test_conf_load_mapping(self):
        dict_conf = {
            "archive_file_pattern": "*.txt",
            "plugin_file": "$plugin_folder/txt",
            "mapping_label": "hello",
            "config_file": "test.cfg",
            "output": ["rawjson"],
        }

        res = load_mapping(copy.deepcopy(dict_conf), 10, True)
        self.assertEqual(dict_conf["config_file"], res.params["config_file"])
        original = copy.deepcopy(dict_conf)
        _ = load_mapping(dict_conf, 10, True)
        self.assertEqual(original, dict_conf)

        bad_copy = copy.deepcopy(dict_conf)
        bad_copy.pop("archive_file_pattern", None)
        result: str
        with self.assertRaises(Exception) as e:
            load_mapping(copy.deepcopy(bad_copy), 10, True)
        result = e.exception.__str__()
        self.assertTrue(
            "Either 'archive_file_pattern' or 'original_file_pattern' must be defined" in result
        )

        bad_copy = copy.deepcopy(dict_conf)
        bad_copy.pop("plugin_file", None)
        with self.assertRaises(Exception) as e:
            load_mapping(copy.deepcopy(bad_copy), 10, True)
        result = e.exception.__str__()
        self.assertTrue("'plugin_file' not found" in result)

        bad_copy = copy.deepcopy(dict_conf)
        bad_copy.pop("mapping_label", None)
        with self.assertRaises(Exception) as e:
            load_mapping(copy.deepcopy(bad_copy), 10, True)
        result = e.exception.__str__()
        self.assertTrue("'mapping_label' not found" in result)

        bad_copy = copy.deepcopy(dict_conf)
        bad_copy.pop("output", None)
        with self.assertRaises(Exception) as e:
            load_mapping(copy.deepcopy(bad_copy), 10, True)
        result = e.exception.__str__()
        self.assertTrue("'output' not found" in result)

    def test_conf_load_output_configuration(self):
        dict_conf = {
            "type": "file",
            "format": "json",
            "date_format": "iso",
            "with_timeline": True,
            "output_folder": ".tmp/",
            "base_file_name": "test",
        }

        res = load_output_configuration(copy.deepcopy(dict_conf))

        self.assertEqual(dict_conf["output_folder"], res.output_folder)
        original = copy.deepcopy(dict_conf)
        _ = load_output_configuration(dict_conf)
        self.assertEqual(original, dict_conf)

        bad_copy = copy.deepcopy(dict_conf)
        bad_copy.pop("type", None)
        with self.assertRaises(Exception) as e:
            load_output_configuration(copy.deepcopy(bad_copy))
        result: str = e.exception.__str__()
        self.assertTrue("'type' not found" in result)

        bad_copy = copy.deepcopy(dict_conf)
        bad_copy.pop("date_format", None)
        with self.assertRaises(Exception) as e:
            load_output_configuration(copy.deepcopy(bad_copy))
        result = e.exception.__str__()
        self.assertTrue("'date_format' not found" in result)

    def test_conf_error(self):
        dict_conf: dict[str, Any] = {
            "plugin_prefixes": ["-ogre-anssi"],
            "case": "test_case",
            "temp_folder": ".tmp",
            "output_folder": ".output",
            "plugin_folder": "test/plugin_folder",
            "mapping": [
                {
                    "archive_file_pattern": "*.txt",
                    "original_file_pattern": "*original.txt",
                    "plugin_file": "txt",
                    "output_name": "sometext",
                    "config_file": "test.cfg",
                    "output": ["rawjson"],
                }
            ],
            "output": {
                "rawjson": {
                    "type": "file",
                    "format": "json",
                    "date_format": "iso",
                    "with_timeline": False,
                    "output_folder": ".tmp/",
                    "base_file_name": "test",
                }
            },
        }

        with self.assertRaises(Exception) as e:
            build_configuration(copy.deepcopy(dict_conf), {})
        result: str = e.exception.__str__()

        self.assertTrue(
            "Only one 'archive_file_pattern' or 'original_file_pattern' must be defined" in result
        )

        dict_conf["temp_folder"] = None
        with self.assertRaises(Exception) as e:
            build_configuration(copy.deepcopy(dict_conf), {})
        result = e.exception.__str__()
        self.assertTrue("'temp_folder' must be defined" in result)

        dict_conf["temp_folder"] = ".tmp"
        dict_conf["output_folder"] = None
        with self.assertRaises(Exception) as e:
            build_configuration(copy.deepcopy(dict_conf), {})
        result = e.exception.__str__()
        self.assertTrue("'output_folder' must be defined" in result)

    def test_conf_external_param(self):
        dict_conf = {
            "plugin_prefixes": ["-ogre-anssi"],
            "case": "testCase",
            "temp_folder": ".tmp",
            "output_folder": ".output",
            "plugin_folder": "$case/conf",
            "mapping": [
                {
                    "archive_file_pattern": "*.txt",
                    "plugin_file": "txt",
                    "mapping_label": "sometext",
                    "config_file": "test.cfg",
                    "output": ["rawjson"],
                }
            ],
            "output": {
                "rawjson": {
                    "type": "file",
                    "format": "json",
                    "date_format": "iso",
                    "with_timeline": False,
                    "output_folder": ".tmp/",
                    "base_file_name": "test",
                }
            },
        }

        global_params = {
            "case": "testGlobalCase",
            "temp_folder": ".global_tmp",
            "output_folder": ".global_output",
        }

        conf = build_configuration(copy.deepcopy(dict_conf), global_params)
        self.assertEqual(conf.case, global_params["case"])

        self.assertTrue(conf.temp_folder.startswith(global_params["temp_folder"]))
        self.assertEqual(conf.output_folder, global_params["output_folder"])

        os.environ["OGRE_CASE"] = ".CASE_ENV"
        os.environ["OGRE_TEMP_FOLDER"] = ".TMP_ENV"
        os.environ["OGRE_OUTPUT_FOLDER"] = ".OUTPUT_ENV"

        try:
            # global_params have priority over environment variables
            conf = build_configuration(copy.deepcopy(dict_conf), global_params)
            self.assertEqual(conf.case, global_params["case"])
            self.assertTrue(conf.temp_folder.startswith(global_params["temp_folder"]))
            self.assertEqual(conf.output_folder, global_params["output_folder"])

            # Environment variables have a priority over what is defined in the configuration file
            conf = build_configuration(copy.deepcopy(dict_conf), {})
            self.assertEqual(conf.case, os.environ["OGRE_CASE"])
            self.assertTrue(conf.temp_folder.startswith(os.environ["OGRE_TEMP_FOLDER"]))
            self.assertEqual(conf.output_folder, os.environ["OGRE_OUTPUT_FOLDER"])
        finally:
            os.environ.pop("OGRE_CASE")
            os.environ.pop("OGRE_TEMP_FOLDER")
            os.environ.pop("OGRE_OUTPUT_FOLDER")

    # output_folder: .tmp/$case/output
    # temp_folder: .tmp/$case/extract
    # report_folder: .tmp/$case/report

    def test_conf_case_wildcard(self):
        dict_conf = {
            "plugin_prefixes": ["-ogre-anssi"],
            "case": "testCase",
            "temp_folder": ".tmp/$case",
            "output_folder": "$case/output",
            "report_folder": "$case_report",
            "plugin_folder": "$case/conf",
            "mapping": [
                {
                    "archive_file_pattern": "*.txt",
                    "plugin_file": "txt",
                    "mapping_label": "sometext",
                    "config_file": "test.cfg",
                    "output": ["rawjson"],
                }
            ],
            "output": {
                "rawjson": {
                    "type": "file",
                    "format": "json",
                    "date_format": "iso",
                    "with_timeline": False,
                    "output_folder": ".tmp/",
                    "base_file_name": "test",
                }
            },
        }

        global_params = {
            "case": "testGlobalCase",
        }
        case = global_params["case"]
        conf = build_configuration(copy.deepcopy(dict_conf), global_params)
        self.assertEqual(conf.case, case)
        self.assertEqual(conf.output_folder, f"{case}/output")
        self.assertEqual(conf.report_folder, f"{case}_report")
        self.assertTrue(conf.temp_folder.startswith(f".tmp/{case}"))
        self.assertEqual(conf.plugin_folder, f"{case}/conf")
