"""C-owned business facts, committed with their actual state transition."""

from uuid import uuid4

from psycopg.types.json import Jsonb


def record_business_event(conn, application, event_type, now, *, operation_id=None):
    payload = {
        "application_id": str(application["id"]),
        "version": application["version"],
        "review_status": application["review_status"],
        "integration_status": application["integration_status"],
    }
    if operation_id is not None:
        payload.update(operation_id=str(operation_id), generation=application["generation"])
    conn.execute(
        "INSERT INTO c_business_events VALUES (%s,%s,%s,%s,%s)",
        (uuid4(), application["id"], event_type, Jsonb(payload), now),
    )
