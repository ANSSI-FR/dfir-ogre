from dataclasses import dataclass

from dfir_ogre_common import BatchEntry


@dataclass
class OgreRunConfiguration:
    batch_entries: list[BatchEntry]
    plugin_file: str
    mapping_label: str
    module: str
    parser: str
    batch: bool
    timeout: int


class RunConfigMap:
    map: dict[str, OgreRunConfiguration]

    def __init__(self) -> None:
        self.map = {}

    def add_configuration(
        self,
        batch_entry: BatchEntry,
        plugin_file: str,
        mapping_label: str,
        module: str,
        parser: str,
        batch: bool,
        timeout: int,
    ) -> None:
        entry = self.map.get(plugin_file)
        if entry:
            entry.batch_entries.append(batch_entry)
            return

        self.map[plugin_file] = OgreRunConfiguration(
            [batch_entry],
            plugin_file,
            mapping_label,
            module,
            parser,
            batch,
            timeout,
        )


@dataclass
class PrepareRunResult:
    archive: str
    runs: RunConfigMap
    errors: list[str]
    computer: str
    orc_id: str
    output_folder: str
    report_folder: str
    tmp_folder: str
