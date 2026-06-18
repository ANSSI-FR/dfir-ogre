from unittest import TestCase

import ogre.commands as commands
import ogre.dfir_orc_unpack as dfir_orc_unpack
from ogre import orc_mapping, orc_metadata, orc_unpacker
from ogre import parser_execution, parser_results


class TestCompatibilityFacades(TestCase):
    def test_dfir_orc_unpack_re_exports_public_orc_types_and_functions(self):
        self.assertIs(dfir_orc_unpack.FileMapping, orc_mapping.FileMapping)
        self.assertIs(dfir_orc_unpack.OriginalNameMapping, orc_mapping.OriginalNameMapping)
        self.assertIs(dfir_orc_unpack.UnpackResult, orc_mapping.UnpackResult)
        self.assertIs(dfir_orc_unpack.OrcOutcome, orc_metadata.OrcOutcome)
        self.assertIs(
            dfir_orc_unpack.load_archive_metadata,
            orc_metadata.load_archive_metadata,
        )
        self.assertIs(dfir_orc_unpack.unpack_dfir_orc, orc_unpacker.unpack_dfir_orc)

    def test_commands_re_exports_public_parser_types_and_functions(self):
        self.assertIs(commands.FileStat, parser_results.FileStat)
        self.assertIs(commands.OutputStat, parser_results.OutputStat)
        self.assertIs(commands.RunResult, parser_results.RunResult)
        self.assertIs(commands.metadata_to_dict, parser_results.metadata_to_dict)
        self.assertIs(commands.run_parser, parser_execution.run_parser)
        self.assertIs(commands.run_batch_parser, parser_execution.run_batch_parser)
