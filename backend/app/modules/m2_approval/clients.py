from enum import StrEnum
from typing import Protocol
from urllib.parse import quote

import httpx

from app.common.auth.domain import ServiceError
from app.modules.m2_approval.domain import Room


class Outcome(StrEnum):
    APPLIED = "APPLIED"
    RELEASED = "RELEASED"
    CONFLICT = "CONFLICT"
    PENDING = "PENDING"
    NOT_FOUND = "NOT_FOUND"


class RemoteUnavailable(Exception):
    """No safe conclusion about the remote write is available."""


class M1Gateway(Protocol):
    def execute(self, payload: dict) -> Outcome: ...
    def query(self, operation_id: str) -> Outcome: ...


class HttpM1Gateway:
    """The host supplies paths only after A/C agree on the wire contract."""

    def __init__(
        self,
        client: httpx.Client,
        *,
        apply_path: str,
        release_path: str,
        query_path: str,
        service_token: str,
        timeout_seconds: float,
    ):
        if (
            not service_token
            or timeout_seconds <= 0
            or "{operation_id}" not in query_path
            or not apply_path
            or not release_path
        ):
            raise ValueError("Explicit M1 paths, credentials and timeout are required")
        self.client, self.apply_path, self.release_path = (
            client,
            apply_path,
            release_path,
        )
        self.query_path, self._token, self.timeout = (
            query_path,
            service_token,
            timeout_seconds,
        )

    def _request(self, method, path, operation_id, payload=None):
        try:
            response = self.client.request(
                method,
                path,
                json=payload,
                headers={
                    "Authorization": "Bearer " + self._token,
                    "Idempotency-Key": operation_id,
                },
                timeout=self.timeout,
                follow_redirects=False,
            )
            if response.status_code not in (200, 201, 202, 409) or len(response.content) > 65536:
                raise RemoteUnavailable("M1_RESPONSE_UNCONFIRMED")
            body = response.json()
            if not isinstance(body, dict) or body.get("operation_id") != operation_id:
                raise RemoteUnavailable("M1_CORRELATION_INVALID")
            outcome = Outcome(body["result"])
            if response.status_code == 202 and outcome not in (
                Outcome.PENDING,
                Outcome.NOT_FOUND,
            ):
                raise RemoteUnavailable("M1_RESPONSE_UNCONFIRMED")
            if response.status_code == 409 and outcome != Outcome.CONFLICT:
                raise RemoteUnavailable("M1_RESPONSE_UNCONFIRMED")
            return outcome
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise RemoteUnavailable("M1_RESPONSE_UNCONFIRMED") from exc

    def execute(self, payload):
        path = self.apply_path if payload["kind"] == "APPLY" else self.release_path
        return self._request("POST", path, payload["operation_id"], payload)

    def query(self, operation_id):
        return self._request(
            "GET",
            self.query_path.replace("{operation_id}", quote(operation_id, safe="")),
            operation_id,
        )


class HttpResourceGateway:
    def __init__(
        self,
        client: httpx.Client,
        *,
        room_path: str,
        service_token: str,
        timeout_seconds: float,
    ):
        if "{room_id}" not in room_path or not service_token or timeout_seconds <= 0:
            raise ValueError("Explicit resource path, credentials and timeout are required")
        self.client, self.path, self._token, self.timeout = (
            client,
            room_path,
            service_token,
            timeout_seconds,
        )

    def get_room(self, room_id):
        try:
            response = self.client.get(
                self.path.replace("{room_id}", quote(room_id, safe="")),
                headers={"Authorization": "Bearer " + self._token},
                timeout=self.timeout,
                follow_redirects=False,
            )
            if response.status_code == 404:
                raise ServiceError(404, "ROOM_NOT_FOUND", "教室不存在或不可见")
            if response.status_code != 200 or len(response.content) > 65536:
                raise ValueError("Unconfirmed resource response")
            body = response.json()
            if (
                not isinstance(body, dict)
                or body.get("id") != room_id
                or not isinstance(body.get("department_id"), str)
                or type(body.get("enabled")) is not bool
            ):
                raise ValueError("Invalid resource response")
            return Room(room_id, body["department_id"], body["enabled"])
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise ServiceError(503, "RESOURCE_UNAVAILABLE", "暂时无法确认教室信息") from exc
