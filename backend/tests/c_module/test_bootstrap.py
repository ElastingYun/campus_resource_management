import json

from app.common.auth import bootstrap
from app.config import Settings

from .test_hosted_runtime import scoped_engine
from .test_runtime_settings import EXAMPLE


def test_explicit_account_command_is_repeatable_and_does_not_echo_password(
    case, tmp_path, monkeypatch, capsys
):
    roles = tmp_path / "roles.json"
    roles.write_text(json.dumps({"applicant": ["m2.submit"]}))
    settings = Settings(
        _env_file=None, db_host="unused.test", db_password="synthetic", c_config_file=EXAMPLE
    )
    monkeypatch.setattr(bootstrap, "Settings", lambda: settings)
    monkeypatch.setattr(bootstrap, "build_engine", lambda _: scoped_engine(case.db))
    password = "synthetic-cli-password"
    monkeypatch.setenv("CAMPUS_BOOTSTRAP_PASSWORD", password)
    args = [
        "--username",
        "cli-user",
        "--department-id",
        "D1",
        "--roles-file",
        str(roles),
        "--role",
        "applicant",
        "--room",
        "R1",
        "--password-env",
        "CAMPUS_BOOTSTRAP_PASSWORD",
    ]
    assert bootstrap.main(args) == 0
    first_output = capsys.readouterr()
    assert bootstrap.main(args) == 0
    second_output = capsys.readouterr()
    assert first_output.out == second_output.out and password not in first_output.out
    roles.write_text(json.dumps({"applicant": ["auth.manage"]}))
    assert bootstrap.main(args) == 1
    assert password not in capsys.readouterr().err
    with case.db.transaction() as conn:
        row = conn.execute(
            "SELECT id,room_ids,all_rooms FROM c_users WHERE username='cli-user'"
        ).fetchone()
        assert row["room_ids"] == ["R1"] and row["all_rooms"] is False
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM c_audit_events "
                "WHERE action='auth.provision' AND target=%s",
                (str(row["id"]),),
            ).fetchone()["n"]
            == 1
        )
