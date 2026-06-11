from unittest import TestCase

from dfir_ogre_common import PluginDescription

from ogre.plugins import PluginDefinition, PluginRegistry


class TestPlugins(TestCase):
    def test_registry_resolves_existing_parser(self):
        registry = PluginRegistry.from_prefixes(["test"])
        plugins = registry.definitions

        self.assertIn("Test", plugins)
        self.assertEqual(plugins["Test"], PluginDefinition("Test", "test", False))

    def test_duplicate_plugin_names_raise(self):
        class FirstParser:
            def description(self):
                return PluginDescription("Duplicate", "first")

        class SecondParser:
            def description(self):
                return PluginDescription("Duplicate", "second")

        registry = PluginRegistry()
        with self.assertRaises(KeyError):
            registry.register_plugin_classes([FirstParser, SecondParser], batch=False)
