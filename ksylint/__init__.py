"""ksylint: lint and format Kaitai Struct .ksy files.

Library API::

    import ksylint
    diags = ksylint.lint_text(text, "foo.ksy")
    fixed = ksylint.fix_text(text, "foo.ksy").text
"""

from .config import Config, load_config
from .diagnostic import Diagnostic, Severity
from .fix import FixResult, fix_text
from .linter import lint_file, lint_text
from .registry import RULES, Rule, all_rules, get_rule

__version__ = "1.0.0.dev0"

__all__ = [
    "RULES",
    "Config",
    "Diagnostic",
    "FixResult",
    "Rule",
    "Severity",
    "__version__",
    "all_rules",
    "fix_text",
    "get_rule",
    "lint_file",
    "lint_text",
    "load_config",
]
