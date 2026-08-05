import importlib.metadata
import json
import logging
from dataclasses import asdict, dataclass, is_dataclass

from typing_extensions import override

from .parser_results import RunResult

logger = logging.getLogger(__name__)


def _get_ogre_version() -> str:
    try:
        return importlib.metadata.version("dfir-ogre")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


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
    ogre_version: str
    computer: str
    orc_id: str
    output_folder: str
    extract_errors: list[str]
    parsing_errors: list[str]
    summary: list[ParserResult]
    run_results: list[RunResult]


class ReportBuilder:
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
    ):
        self.timestamp = timestamp
        self.command_line = command_line
        self.computer = computer
        self.orc_id = orc_id
        self.output_folder = output_folder
        self.extract_errors = []
        self.parsing_errors = []
        self.run_results = []
        self.summary_builder = {}

    def add_extract_error(self, error: str):
        self.extract_errors.append(error)

    def add_parsing_error(self, error: str):
        self.parsing_errors.append(error)

    def add_result(self, result: RunResult, file):
        self.run_results.append(result)

        parser_result = self.summary_builder.get(result.mapping_label, None)
        if not parser_result:
            parser_result = ParserResult(result.mapping_label, 0, 0, 0.0, [])
        parser_result.runs += 1
        parser_result.rows += result.rows
        parser_result.time += result.time_s

        if result.last_error:
            error = f"{result.num_errors} error(s) occurred while parsing data: '{result.mapping_label}', file: '{file}', parser: '{result.parser}', last error: {result.last_error}"
            logger.error(error)
            parser_result.errors.append(error)
            self.parsing_errors.append(error)

        self.summary_builder[result.mapping_label] = parser_result

    def get_report(self) -> ArchiveReport:
        summary = []
        for val in self.summary_builder.values():
            summary.append(val)
        summary.sort(key=lambda x: x.parser)

        return ArchiveReport(
            self.timestamp,
            self.command_line,
            _get_ogre_version(),
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
    def default(self, o):
        if is_dataclass(o):
            return asdict(o)  # ignore  # pyright: ignore[reportArgumentType]
        return super().default(o)
