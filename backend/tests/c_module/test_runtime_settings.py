import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app
from app.modules.m2_approval.settings import ComponentConfiguration

EXAMPLE = (
    Path(__file__).resolve().parents[2] / "app/modules/m2_approval/examples/runtime.synthetic.json"
)


@pytest.fixture
def policy_payload():
    return json.loads(EXAMPLE.read_text())


def test_component_is_opt_in_and_requires_database_and_policy():
    assert Settings(_env_file=None).c_enabled is False
    with pytest.raises(ValidationError):
        Settings(_env_file=None, c_enabled=True)


def test_explicit_example_is_configuration_not_an_implicit_default(policy_payload):
    configured = ComponentConfiguration.model_validate_json(json.dumps(policy_payload))
    assert configured.workflow.version == "synthetic-example-only-v1"
    assert configured.submission.max_duration_seconds is None
    assert configured.m1 is None and configured.access_management is None
    del policy_payload["workflow"]["deadline_inclusive"]
    with pytest.raises(ValidationError):
        ComponentConfiguration.model_validate_json(json.dumps(policy_payload))


@pytest.mark.parametrize("field", ["allow_self_review", "allow_revocation", "deadline_inclusive"])
def test_runtime_boolean_strings_are_rejected(policy_payload, field):
    policy_payload["workflow"][field] = "false"
    with pytest.raises(ValidationError):
        ComponentConfiguration.model_validate_json(json.dumps(policy_payload))


@pytest.mark.parametrize(
    "path", ["//another-host/rooms/{room_id}", "https://another-host/{room_id}"]
)
def test_resource_path_cannot_redirect_service_credentials(policy_payload, path):
    policy_payload["resources"]["room_path"] = path
    with pytest.raises(ValidationError):
        ComponentConfiguration.model_validate_json(json.dumps(policy_payload))


def test_policy_error_does_not_echo_raw_input_or_secret(tmp_path, policy_payload):
    secret = "synthetic-secret-not-to-echo"
    policy_payload["resources"]["base_url"] = f"http://user:{secret}@example.test"
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(policy_payload))
    with pytest.raises(ValueError) as error:
        ComponentConfiguration.from_file(path)
    assert secret not in str(error.value)


def test_m1_lease_covers_query_and_write_timeout(policy_payload):
    policy_payload["m1"] = {
        "base_url": "http://m1.contract.test",
        "token_env": "CAMPUS_M1_SERVICE_TOKEN",
        "timeout_seconds": 2.0,
        "apply_path": "/apply",
        "release_path": "/release",
        "query_path": "/operations/{operation_id}",
        "lease_seconds": 4.0,
        "retry_delay_seconds": 1.0,
        "max_attempts": 3,
    }
    with pytest.raises(ValidationError):
        ComponentConfiguration.model_validate_json(json.dumps(policy_payload))
    policy_payload["m1"]["lease_seconds"] = 5.0
    assert ComponentConfiguration.model_validate_json(json.dumps(policy_payload)).m1 is not None


def test_service_credentials_load_from_dotenv_without_entering_repr(tmp_path, monkeypatch):
    for key in (
        "CAMPUS_RESOURCES_SERVICE_TOKEN",
        "CAMPUS_M1_SERVICE_TOKEN",
        "CAMPUS_C_CONFIG_FILE",
    ):
        monkeypatch.delenv(key, raising=False)
    secret = "synthetic-dotenv-service-token"
    path = tmp_path / ".env"
    path.write_text(
        f"CAMPUS_RESOURCES_SERVICE_TOKEN={secret}\nCAMPUS_M1_SERVICE_TOKEN=\nCAMPUS_C_CONFIG_FILE=\n"
    )
    configuration = Settings(_env_file=path, c_enabled=False)
    assert configuration.resources_service_token.get_secret_value() == secret
    assert secret not in repr(configuration)
    assert configuration.m1_service_token is None and configuration.c_config_file is None


@pytest.mark.parametrize("secret", ["synthetic token", "synthetic\ntoken", "合成-token"])
def test_runtime_rejects_invalid_header_credentials_without_echo(secret):
    configuration = Settings(
        _env_file=None,
        c_enabled=True,
        c_config_file=EXAMPLE,
        db_host="unused.test",
        db_password="synthetic",
        resources_service_token=secret,
    )
    with pytest.raises(ValueError) as error:
        create_app(configuration)
    assert secret not in str(error.value)
