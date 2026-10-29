"""B-owned resource management; mount only after identity/schema integration is approved."""

from app.modules.resources.router import create_resources_router

__all__ = ["create_resources_router"]
