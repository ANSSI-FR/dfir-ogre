from unittest import TestCase

from ogre.commands import FileStat as CommandsFileStat
from ogre.commands import OutputStat as CommandsOutputStat
from ogre.commands import RunResult as CommandsRunResult
from ogre.commands import metadata_to_dict as commands_metadata_to_dict
from ogre.commands import run_batch_parser as commands_run_batch_parser
from ogre.commands import run_parser as commands_run_parser
from ogre.parser_execution import run_batch_parser, run_parser
from ogre.parser_results import FileStat, OutputStat, RunResult, metadata_to_dict


class TestParserExecution(TestCase):
    def test_commands_re_exports_parser_execution_functions(self):
        self.assertIs(commands_run_parser, run_parser)
        self.assertIs(commands_run_batch_parser, run_batch_parser)

    def test_commands_re_exports_run_result_type(self):
        self.assertIs(CommandsFileStat, FileStat)
        self.assertIs(CommandsOutputStat, OutputStat)
        self.assertIs(CommandsRunResult, RunResult)
        self.assertIs(commands_metadata_to_dict, metadata_to_dict)
