from dfir_ogre_common import (
    Metadata,
    OgrePlugin,
    Output,
    PluginConfiguration,
    PluginDescription,
    Record,
    RunConfiguration,
    RunReport,
    Value,
)


class SampleTexLine(OgrePlugin):
    def description(self) -> PluginDescription:
        return PluginDescription("SampleText", "Send text lines into output")

    def parse(
        self,
        input_file: str,
        plugin_file: str,
        run_config: RunConfiguration,
        metadata: Metadata,
    ) -> RunReport:
        run_report = RunReport()
        plugin_config = PluginConfiguration.load(plugin_file)
        with open(input_file) as input:
            with Output(run_config, plugin_config, metadata) as output:
                record = Record()
                for line in input:
                    record.add("line", Value.String(line.strip()))
                    output.write(record)

                run_report.add_output_report(output.get_report())
        return run_report
