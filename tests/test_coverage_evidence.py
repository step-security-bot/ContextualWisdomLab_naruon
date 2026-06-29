import pytest

from backend.core.version import _version_file_candidates, get_release_version


@pytest.fixture(autouse=True)
def clear_version_cache():
    get_release_version.cache_clear()
    yield
    get_release_version.cache_clear()


def test_get_release_version_from_first_existing_candidate(tmp_path, monkeypatch):
    missing_candidate = tmp_path / "missing.VERSION"
    present_candidate = tmp_path / "VERSION"
    present_candidate.write_text(" 1.2.3 \n", encoding="utf-8")

    monkeypatch.setattr(
        "backend.core.version._version_file_candidates",
        lambda: (missing_candidate, present_candidate),
    )

    assert get_release_version() == "1.2.3"


def test_version_file_candidates_include_repository_root():
    assert _version_file_candidates()[0].name == "VERSION"


def test_get_release_version_reports_checked_candidates(tmp_path, monkeypatch):
    missing_candidate = tmp_path / "missing.VERSION"

    monkeypatch.setattr(
        "backend.core.version._version_file_candidates",
        lambda: (missing_candidate,),
    )

    with pytest.raises(RuntimeError, match="release VERSION file is missing; checked:"):
        get_release_version()
