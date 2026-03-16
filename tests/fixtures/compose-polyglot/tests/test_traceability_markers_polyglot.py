import pytest


@pytest.mark.req("FR-001")
def test_fixture_requirement_marker() -> None:
    assert True

