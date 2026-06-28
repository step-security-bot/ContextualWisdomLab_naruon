import pytest

from core.version import get_release_version


@pytest.fixture(autouse=True)
def clear_version_cache():
    get_release_version.cache_clear()
    yield
    get_release_version.cache_clear()


def test_get_release_version_success(tmp_path, monkeypatch):
    missing_candidate = tmp_path / "VERSION1"
    present_candidate = tmp_path / "VERSION2"

    present_candidate.write_text(" 1.2.3 \n", encoding="utf-8")

    monkeypatch.setattr(
        "core.version._version_file_candidates",
        lambda: (missing_candidate, present_candidate),
    )

    assert get_release_version() == "1.2.3"


def test_get_release_version_failure(tmp_path, monkeypatch):
    missing_candidate = tmp_path / "VERSION1"

    monkeypatch.setattr(
        "core.version._version_file_candidates",
        lambda: (missing_candidate,),
    )

    with pytest.raises(RuntimeError, match="release VERSION file is missing; checked:"):
        get_release_version()
