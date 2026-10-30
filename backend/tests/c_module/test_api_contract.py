import json
from pathlib import Path


def test_published_c_contract_matches_routes_and_does_not_lose_security(case):
    path = Path(__file__).resolve().parents[3] / "docs/architecture/c-v1-openapi.json"
    published = json.loads(path.read_text())
    actual = case.app.openapi()
    prefixes = ("/api/v1/auth/", "/api/v1/m2/", "/api/v1/audit/")
    paths = {key: value for key, value in published["paths"].items() if key.startswith(prefixes)}
    assert paths == actual["paths"]
    for name, schema in actual["components"]["schemas"].items():
        assert published["components"]["schemas"][name] == schema
    assert published["components"]["securitySchemes"]["HTTPBearer"]["scheme"] == "bearer"
    submit = paths["/api/v1/m2/applications"]["post"]
    assert submit["security"] == [{"HTTPBearer": []}]
    assert any(
        item["name"] == "Idempotency-Key" and item["required"] for item in submit["parameters"]
    )
    assert submit["responses"]["503"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/ErrorView"
    )
