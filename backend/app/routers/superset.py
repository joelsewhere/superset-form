"""Mints Superset guest tokens for embedded dashboards.

Flow, per the Superset embedded SDK contract:

  1. Log in to Superset as a service account -> access token.
  2. Exchange that for a *guest* token scoped to one dashboard.
  3. Hand the guest token to the browser, which passes it to the iframe.

The SDK re-invokes this automatically before each guest token expires (~5
minutes), so it is called repeatedly for the life of a page. The token is
scoped per dashboard binding, since a view can show several dashboards at once.

SECURITY: this endpoint is unauthenticated, which is acceptable only because
this is a local development stack. As written it will mint a dashboard token
for anyone who can reach it. Any real deployment must put the application's own
authentication in front of it, pass the authenticated user through to the
`user` field below, and populate `rls` for row-level security.
"""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import store
from app.db import get_session
from app.schemas import GuestTokenResponse
from app.superset_client import SupersetClient, SupersetError, SupersetUnreachable

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/superset", tags=["superset"])


@router.post("/guest-token/{binding_id}", response_model=GuestTokenResponse)
async def create_guest_token(
    binding_id: int,
    session: AsyncSession = Depends(get_session),
) -> GuestTokenResponse:
    binding = await store.get_dashboard(session, binding_id)
    if binding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such dashboard binding.")

    if not binding.embed_uuid:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"Dashboard {binding.name!r} has no embed UUID yet. Open Setup "
                "and run 'Repair' on it, or enable embedding in Superset."
            ),
        )

    async with httpx.AsyncClient(timeout=15.0) as http:
        client = SupersetClient(http)
        try:
            response = await client.request(
                "POST",
                "/api/v1/security/guest_token/",
                json={
                    "resources": [
                        {
                            # Must be the embed UUID, not the numeric id.
                            "type": "dashboard",
                            "id": binding.embed_uuid,
                        }
                    ],
                    "rls": [],
                    "user": {
                        "username": "frontflow-guest",
                        "first_name": "FrontFlow",
                        "last_name": "Guest",
                    },
                },
            )
        except SupersetUnreachable as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Could not reach Superset: {exc}",
            ) from exc
        except SupersetError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
            ) from exc

        if response.status_code != 200:
            logger.error(
                "Guest token request failed: %s %s", response.status_code, response.text
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Superset refused to issue a guest token.",
            )

        return GuestTokenResponse(token=response.json()["token"])
