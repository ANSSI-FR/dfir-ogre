from unittest import TestCase

from ogre.commands import RunResult as CommandsRunResult
from ogre.commands import run_batch_parser as commands_run_batch_parser
from ogre.commands import run_parser as commands_run_parser
from ogre.parser_execution import run_batch_parser, run_parser
from ogre.parser_results import RunResult


class TestParserExecution(TestCase):
    def test_commands_re_exports_parser_execution_functions(self):
        self.assertIs(commands_run_parser, run_parser)
        self.assertIs(commands_run_batch_parser, run_batch_parser)

    def test_commands_re_exports_run_result_type(self):
        self.assertIs(CommandsRunResult, RunResult)
