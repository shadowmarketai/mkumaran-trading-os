"""Shared router dependencies.

Objects defined here are imported by both `mcp_server.mcp_server` and the
per-domain router modules, so they can't live in `mcp_server.mcp_server`
without creating a circular-import headache.

Current contents:
    - `limiter` : slowapi Limiter singleton used by @limiter.limit(...)
                  decorators across routers.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
