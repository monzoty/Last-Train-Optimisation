import pytest

from testcases import ALL


@pytest.mark.parametrize("case", ALL, ids=[f.__name__ for f in ALL])
def test_case(case):
    result = case()
    assert result["Result"] in ("PASS", "OPEN ISSUE"), result
