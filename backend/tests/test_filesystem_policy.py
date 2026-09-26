from pathlib import Path

import pytest

from backend.filesystem_policy import (
    FileOperation,
    ONE_DRIVE_MESSAGE,
    authorize_path,
)
from backend.tools import FileReadArguments, _file_read, _file_search
from backend.rag import RAGPipeline


def test_allowed_local_roots_can_be_read():
    assert authorize_path(Path("C:/nikola"), FileOperation.READ).is_dir()


def test_nikola_can_create_and_search_allowed_file():
    test_dir = Path("C:/nikola/backend/tests/.filesystem-policy")
    test_dir.mkdir(parents=True, exist_ok=True)
    test_file = test_dir / "policy-search.txt"
    try:
        authorized = authorize_path(test_file, FileOperation.WRITE)
        authorized.write_text("allowed local search marker", encoding="utf-8")
        read_result = _file_read(FileReadArguments(path=str(test_file)))
        search_result = _file_search(
            type("SearchArgs", (), {
                "root": str(test_dir),
                "query": "policy-search",
                "extension": ".txt",
                "limit": 20,
            })()
        )
        assert read_result["content"] == "allowed local search marker"
        assert search_result["count"] == 1
    finally:
        test_file.unlink(missing_ok=True)
        test_dir.rmdir()


@pytest.mark.parametrize(
    "raw_path",
    [
        str(Path.home() / "OneDrive" / "blocked.txt"),
        str(Path.home() / "Desktop" / ".." / "OneDrive" / "blocked.txt"),
        r"C:\Users\harsha\OneDrive\blocked.txt",
    ],
)
def test_onedrive_is_blocked_for_all_operations(raw_path):
    for operation in FileOperation:
        with pytest.raises(PermissionError, match=ONE_DRIVE_MESSAGE):
            authorize_path(raw_path, operation)


def test_symlink_resolving_into_onedrive_is_blocked():
    link = Path("C:/nikola/backend/tests/.onedrive-link")
    try:
        link.symlink_to(Path.home() / "OneDrive", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is unavailable on this Windows test host")

    try:
        with pytest.raises(PermissionError, match=ONE_DRIVE_MESSAGE):
            authorize_path(link / "blocked.txt", FileOperation.READ)
    finally:
        link.unlink(missing_ok=True)


def test_rag_indexing_rejects_onedrive_before_reading():
    rag = RAGPipeline.__new__(RAGPipeline)
    with pytest.raises(PermissionError, match=ONE_DRIVE_MESSAGE):
        rag._index_file_sync(str(Path.home() / "OneDrive" / "blocked.txt"))
