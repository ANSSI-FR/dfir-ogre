from dfir_ogre_common import (
    Metadata,
    OgrePlugin,
    PluginDescription,
    RunConfiguration,
    RunReport,
)


class VoidParser(OgrePlugin):
    def description(self) -> PluginDescription:
        return PluginDescription("Void", "This parser does nothing!")

    def parse(
        self,
        input_file: str,
        plugin_file: str,
        run_config: RunConfiguration,
        metadata: Metadata,
    ) -> RunReport:
      return RunReport()
