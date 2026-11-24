import pathlib

import pytest

HERE = pathlib.Path(__file__).parent
FIXTURES = HERE / "fixtures"
RULE_FIXTURES = FIXTURES / "rules"
FIX_FIXTURES = FIXTURES / "fix"
FORMATS = HERE / "data" / "formats"


@pytest.fixture
def all_rules_config():
    import ksylint

    return ksylint.Config(select=["ALL"])
