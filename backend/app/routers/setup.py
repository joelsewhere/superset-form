"""Superset discovery, backing the Setup panel.

Read-only reconnaissance against a live Superset: is it up, what dashboards
exist, is a given one embeddable, and what native filters does it have. The
results feed the pickers in Setup so nothing has to be copied by hand.

Persisted configuration lives on dashboard bindings (app/routers/dashboards.py),
not here.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException, status

from app.config import get_settings
from app.schemas import (
    EnableEmbeddingRequest,
    SupersetDashboard,
    SupersetNativeFilter,
    SupersetStatus,
)
from app.superset_client import SupersetClient, SupersetError, SupersetUnreachable

router = APIRouter(prefix="/api", tags=["setup"])

_TIMEOUT = httpx.Timeout(15.0)


def _translate(exc: Exception) -> HTTPException:
    """Map client errors onto responses the setup page can render usefully."""
    if isinstance(exc, SupersetUnreachable):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"Could not reach Superset at {get_settings().superset_url}. "
                f"Check that the service is up. ({exc})"
            ),
        )
    if isinstance(exc, SupersetError):
        return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


# --- Superset discovery ----------------------------------------------------


@router.get("/superset/status", response_model=SupersetStatus)
async def superset_status() -> SupersetStatus:
    """Ping Superset and confirm the service account can authenticate.

    Never raises: an unreachable Superset is the normal state before setup is
    finished, and the page needs to render that rather than an error.
    """
    settings = get_settings()
    async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
        client = SupersetClient(http)
        try:
            result = await client.ping()
            return SupersetStatus(url=settings.superset_url, **result)
        except SupersetUnreachable as exc:
            return SupersetStatus(
                reachable=False,
                authenticated=False,
                url=settings.superset_url,
                detail=f"Could not reach Superset: {exc}",
            )
        except SupersetError as exc:
            return SupersetStatus(
                reachable=True,
                authenticated=False,
                url=settings.superset_url,
                detail=str(exc),
            )


@router.get("/superset/dashboards", response_model=list[SupersetDashboard])
async def list_dashboards() -> list[SupersetDashboard]:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
        try:
            return [
                SupersetDashboard(**d)
                for d in await SupersetClient(http).list_dashboards()
            ]
        except Exception as exc:
            raise _translate(exc) from exc


@router.get("/superset/dashboards/{dashboard_id}/embedded")
async def get_embedded(dashboard_id: str) -> dict[str, str | None]:
    """The dashboard's embed UUID, or null when embedding is not yet enabled."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
        try:
            return {"uuid": await SupersetClient(http).get_embedded_uuid(dashboard_id)}
        except Exception as exc:
            raise _translate(exc) from exc


@router.post("/superset/dashboards/{dashboard_id}/embedded")
async def enable_embedded(
    dashboard_id: str,
    payload: EnableEmbeddingRequest,
) -> dict[str, str]:
    """Enable embedding and return the UUID, so nobody has to copy it by hand."""
    settings = get_settings()
    domains = payload.allowed_domains or settings.cors_origin_list

    async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
        try:
            uuid = await SupersetClient(http).enable_embedding(dashboard_id, domains)
            return {"uuid": uuid}
        except Exception as exc:
            raise _translate(exc) from exc


@router.get(
    "/superset/dashboards/{dashboard_id}/filters",
    response_model=list[SupersetNativeFilter],
)
async def list_filters(dashboard_id: str) -> list[SupersetNativeFilter]:
    """Native filters on the dashboard, for picking the one to drive."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
        try:
            return [
                SupersetNativeFilter(**f)
                for f in await SupersetClient(http).list_native_filters(dashboard_id)
            ]
        except Exception as exc:
            raise _translate(exc) from exc
