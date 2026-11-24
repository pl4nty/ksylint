"""Diagnostic and severity types."""

from __future__ import annotations

import enum
from dataclasses import asdict, dataclass
from typing import Any, Optional


class Severity(str, enum.Enum):
    """How serious a diagnostic is."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"

    @property
    def rank(self) -> int:
        return {"error": 3, "warning": 2, "info": 1}[self.value]

    @classmethod
    def parse(cls, value: str | Severity) -> Severity:
        if isinstance(value, Severity):
            return value
        try:
            return cls(str(value).lower())
        except ValueError:
            raise ValueError(
                f"unknown severity {value!r} (expected error, warning or info)"
            ) from None

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class Diagnostic:
    """A single problem found in a .ksy file.

    ``line`` and ``column`` are 1-based. ``path`` is a JSON-pointer-like path
    into the YAML document (for example ``/types/foo/seq/2/type``); it is an
    empty string for problems that are not tied to a YAML node.
    """

    rule_id: str
    rule_name: str
    severity: Severity
    message: str
    file: str
    line: int
    column: int
    path: str = ""
    end_line: Optional[int] = None
    end_column: Optional[int] = None
    fixable: bool = False
    url: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["severity"] = self.severity.value
        return d

    def __str__(self) -> str:
        return (
            f"{self.file}:{self.line}:{self.column}: {self.severity.value} "
            f"[{self.rule_id} {self.rule_name}] {self.message}"
        )

    @property
    def sort_key(self) -> tuple:
        return (self.file, self.line, self.column, self.rule_id, self.message)
