import pytest


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    monkeypatch.setenv("LEAKLENS_STORAGE", "sqlite")
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    monkeypatch.setenv("LEAKLENS_DB_PATH", str(tmp_path / "test.sqlite3"))
