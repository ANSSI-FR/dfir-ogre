from unittest import TestCase

from dfir_ogre_common import PluginDescription

from ogre.plugins import PluginDefinition, _register_plugin_classes, load_plugins


class TestPlugins(TestCase):
    def test_load_plugins_resolves_existing_parser(self):
        plugins = load_plugins(["test"])

        self.assertIn("Test", plugins)
        self.assertEqual(plugins["Test"], PluginDefinition("Test", "test", False))

    def test_duplicate_plugin_names_raise(self):
        class FirstParser:
            def description(self):
                return PluginDescription("Duplicate", "first")

        class SecondParser:
            def description(self):
                return PluginDescription("Duplicate", "second")

        with self.assertRaises(KeyError):
            _register_plugin_classes({}, [FirstParser, SecondParser], batch=False)
