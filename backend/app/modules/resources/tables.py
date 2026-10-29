"""SQL reference mapping compatible with A's provisional PR #18 tables.

This module NEVER creates or migrates application tables. The metadata is used
for queries and isolated tests; the authoritative shared migration remains an
A/B/D integration decision. SQLite's integer variant is exclusively for unit tests.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Time,
    UniqueConstraint,
    func,
)

metadata = MetaData()
identifier_type = BigInteger().with_variant(Integer, "sqlite")
rooms = Table(
    "rooms",
    metadata,
    Column("id", identifier_type, primary_key=True, autoincrement=True),
    Column("code", String(32), nullable=False, unique=True),
    Column("name", String(100), nullable=False),
    Column("location", String(200), nullable=False),
    Column("access_scope", String(16), nullable=False),
    Column("department_id", String(64)),
    Column("open_time", Time, nullable=False),
    Column("close_time", Time, nullable=False),
    Column("enabled", Boolean, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("access_scope IN ('campus', 'department')"),
    CheckConstraint("access_scope = 'campus' OR department_id IS NOT NULL"),
    CheckConstraint("open_time < close_time"),
)
seats = Table(
    "seats",
    metadata,
    Column("id", identifier_type, primary_key=True, autoincrement=True),
    Column("room_id", identifier_type, ForeignKey("rooms.id"), nullable=False, index=True),
    Column("code", String(32), nullable=False),
    Column("outlet_type", String(16), nullable=False),
    Column("enabled", Boolean, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("room_id", "code"),
    CheckConstraint("outlet_type IN ('none', 'fixed', 'rail')"),
)
