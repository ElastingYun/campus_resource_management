import json
import multiprocessing
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest

from app.common.auth.domain import ServiceError
from app.modules.m2_approval.clients import (
    HttpM1Gateway,
    HttpResourceGateway,
    Outcome,
    RemoteUnavailable,
)

from .test_worker import passed, worker


@pytest.mark.parametrize(
    "response",
    [
        {"operation_id": "wrong", "result": "APPLIED"},
        {"operation_id": "op", "result": "unknown-enum"},
        {"operation_id": "op"},
        ["unexpected"],
    ],
)
def test_invalid_remote_confirmation_is_unknown(response):
    with httpx.Client(
        base_url="http://contract.test",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response)),
    ) as client:
        gateway = HttpM1Gateway(
            client,
            apply_path="/apply",
            release_path="/release",
            query_path="/operations/{operation_id}",
            service_token="synthetic-token",
            timeout_seconds=1,
        )
        with pytest.raises(RemoteUnavailable):
            gateway.execute({"operation_id": "op", "kind": "APPLY"})


def test_timeout_does_not_mean_rejected():
    def timeout(request):
        raise httpx.ReadTimeout("synthetic timeout", request=request)

    with httpx.Client(
        base_url="http://contract.test", transport=httpx.MockTransport(timeout)
    ) as client:
        gateway = HttpM1Gateway(
            client,
            apply_path="/apply",
            release_path="/release",
            query_path="/operations/{operation_id}",
            service_token="synthetic-token",
            timeout_seconds=1,
        )
        with pytest.raises(RemoteUnavailable):
            gateway.execute({"operation_id": "op", "kind": "APPLY"})


@pytest.mark.parametrize("enabled", ["true", 1, None])
def test_resource_adapter_rejects_ambiguous_enabled(enabled):
    with httpx.Client(
        base_url="http://resources.test",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"id": "R1", "department_id": "D1", "enabled": enabled}
            )
        ),
    ) as client:
        resources = HttpResourceGateway(
            client,
            room_path="/rooms/{room_id}",
            service_token="synthetic-token",
            timeout_seconds=1,
        )
        with pytest.raises(ServiceError) as error:
            resources.get_room("R1")
        assert error.value.status == 503


def _serve_contract(pipe):
    results = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, body):
            encoded = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_POST(self):
            if self.headers.get("Authorization") != "Bearer synthetic-token":
                self.send_error(403)
                return
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            operation_id = body["operation_id"]
            result = "APPLIED" if body["kind"] == "APPLY" else "RELEASED"
            results.setdefault(operation_id, result)
            self.respond({"operation_id": operation_id, "result": results[operation_id]})

        def do_GET(self):
            operation_id = self.path.rsplit("/", 1)[-1]
            self.respond(
                {
                    "operation_id": operation_id,
                    "result": results.get(operation_id, "NOT_FOUND"),
                }
            )

    server = HTTPServer(("127.0.0.1", 0), Handler)
    pipe.send(server.server_port)
    pipe.close()
    server.serve_forever()


def test_separate_process_http_apply_and_release(case):
    # This proves the adapter's real socket transport, NOT integration with A's service.
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(target=_serve_contract, args=(child,))
    process.start()
    child.close()
    try:
        assert parent.poll(10), "Contract server failed to start"
        port = parent.recv()
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False) as client:
            gateway = HttpM1Gateway(
                client,
                apply_path="/apply",
                release_path="/release",
                query_path="/operations/{operation_id}",
                service_token="synthetic-token",
                timeout_seconds=2,
            )
            application = passed(case)
            assert worker(case, gateway).run_once()
            current = case.approval.get(case.principals["student"], application["id"])
            assert current["effective"]
            with case.db.transaction() as conn:
                operation = conn.execute(
                    "SELECT id FROM c_m1_operations WHERE kind='APPLY'"
                ).fetchone()
            assert gateway.query(str(operation["id"])) == Outcome.APPLIED
            case.approval.revoke(
                case.principals["first"],
                application["id"],
                expected_version=current["version"],
                key="revoke",
                request_id="revoke",
            )
            assert worker(case, gateway).run_once()
            assert (
                case.approval.get(case.principals["student"], application["id"])[
                    "integration_status"
                ]
                == "RELEASED"
            )
    finally:
        parent.close()
        process.terminate()
        process.join(timeout=10)
        if process.is_alive():
            process.kill()
            process.join(timeout=5)
