from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, is_dataclass
from typing import TYPE_CHECKING, Any

from typing_extensions import override

if TYPE_CHECKING:
    from .execution.parser_execution import RunResult

logger = logging.getLogger(__name__)


@dataclass
class ParserResult:
    """Aggregated statistics for a single parser across many files."""

    parser: str
    runs: int
    rows: int
    time: float
    errors: list[str]


@dataclass
class ArchiveReport:
    """JSON-serialisable report for an ORC processing run."""

    timestamp: str
    command_line: str
    computer: str
    orc_id: str
    output_folder: str
    extract_errors: list[str]
    parsing_errors: list[str]
    summary: list[ParserResult]
    run_results: list[RunResult]


class ReportBuilder:
    """
    Helper class that incrementally builds an :class:`ArchiveReport`.

    It collects extraction errors, parsing errors, per-parser statistics, and
    individual ``RunResult`` objects. When all processing is complete,
    ``get_report`` returns a JSON-ready dataclass.
    """

    timestamp: str
    command_line: str
    computer: str
    orc_id: str
    output_folder: str
    extract_errors: list[str]
    parsing_errors: list[str]
    run_results: list[RunResult]
    summary_builder: dict[str, ParserResult]

    def __init__(
        self,
        timestamp: str,
        command_line: str,
        computer: str,
        orc_id: str,
        output_folder: str,
    ) -> None:
        self.timestamp = timestamp
        self.command_line = command_line
        self.computer = computer
        self.orc_id = orc_id
        self.output_folder = output_folder
        self.extract_errors = []
        self.parsing_errors = []
        self.run_results = []
        self.summary_builder = {}

    def add_extract_error(self, error: str) -> None:
        self.extract_errors.append(error)

    def add_parsing_error(self, error: str) -> None:
        self.parsing_errors.append(error)

    def add_result(self, result: RunResult, file: str) -> None:
        self.run_results.append(result)

        parser_result = self.summary_builder.get(result.mapping_label)
        if not parser_result:
            parser_result = ParserResult(result.mapping_label, 0, 0, 0.0, [])
        parser_result.runs += 1
        parser_result.rows += result.rows
        parser_result.time += result.time_s

        if result.last_error:
            error = (
                f"{result.num_errors} error(s) occurred while parsing data: "
                f"'{result.mapping_label}', file: '{file}', parser: '{result.parser}', "
                f"last error: {result.last_error}"
            )
            logger.error(error)
            parser_result.errors.append(error)
            self.parsing_errors.append(error)

        self.summary_builder[result.mapping_label] = parser_result

    def get_report(self) -> ArchiveReport:
        summary = list(self.summary_builder.values())
        summary.sort(key=lambda x: x.parser)

        return ArchiveReport(
            self.timestamp,
            self.command_line,
            self.computer,
            self.orc_id,
            self.output_folder,
            self.extract_errors,
            self.parsing_errors,
            summary,
            self.run_results,
        )


class DataclassJSONEncoder(json.JSONEncoder):
    """JSON encoder capable of serialising dataclass instances."""

    @override
    def default(self, o: Any) -> Any:
        if is_dataclass(o) and not isinstance(o, type):
            return asdict(o)
        return super().default(o)
