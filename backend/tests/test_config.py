import pytest
from pydantic import ValidationError

from app.config import Settings
from app.database import build_engine


@pytest.mark.parametrize("port", [0, 65536, "invalid"])
def test_rejects_invalid_database_port(port):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, db_port=port)


def test_password_is_redacted_and_url_handles_special_characters():
    settings = Settings(
        _env_file=None,
        db_host="localhost",
        db_password="synthetic-p@ss:/?#word",
    )
    assert "synthetic-p@ss" not in repr(settings)
    engine = build_engine(settings)
    try:
        assert engine.url.password == "synthetic-p@ss:/?#word"
        assert engine.dialect.name == "postgresql"
        assert "synthetic-p@ss" not in str(engine.url)
    finally:
        engine.dispose()
