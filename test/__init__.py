import os

from dfir_ogre_common import (
    Metadata,
    OgrePlugin,
    PluginDescription,
    RunConfiguration,
    RunReport,
)
from typing_extensions import override

TEMP_FOLDER = os.path.join(".tmp")

PLUGIN_FOLDER = os.path.join("test", "plugin_config")


class TestParser(OgrePlugin):
    @override
    def description(self) -> PluginDescription:
        return PluginDescription("Test", "Test parser")

    @override
    def parse(
        self,
        input_file: str,
        plugin_file: str,
        run_config: RunConfiguration,
        metadata: Metadata,
    ) -> RunReport:
        return RunReport()
