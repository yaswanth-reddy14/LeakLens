import pytest
from backend.main import storage_mode


def test_cloud_lambda_still_rejects_sqlite(monkeypatch):
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "production")
    monkeypatch.setenv("LEAKLENS_SAM_LOCAL_DEMO", "true")
    monkeypatch.delenv("AWS_SAM_LOCAL", raising=False)
    with pytest.raises(RuntimeError):
        storage_mode()


def test_sam_local_requires_explicit_opt_in_and_temporary_path(monkeypatch):
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "local")
    monkeypatch.setenv("AWS_SAM_LOCAL", "true")
    monkeypatch.delenv("LEAKLENS_SAM_LOCAL_DEMO", raising=False)
    with pytest.raises(RuntimeError):
        storage_mode()
    monkeypatch.setenv("LEAKLENS_SAM_LOCAL_DEMO", "true")
    for invalid in ("data/leaklens.sqlite3", "/tmp/leaklens-local/../other.sqlite3"):
        monkeypatch.setenv("LEAKLENS_DB_PATH", invalid)
        with pytest.raises(RuntimeError):
            storage_mode()
    monkeypatch.setenv("LEAKLENS_DB_PATH", "/tmp/leaklens-local/demo.sqlite3")
    assert storage_mode() == "sqlite"
