"""Dashboard bindings: Superset dashboards this app can embed."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import provisioning, store
from app.config import get_settings
from app.db import get_session
from app.schemas import (
    DashboardBindingCreate,
    DashboardBindingRead,
    DashboardBindingUpdate,
)
from app.superset_client import SupersetClient, SupersetError, SupersetUnreachable

router = APIRouter(prefix="/api/dashboards", tags=["dashboards"])


@router.get("", response_model=list[DashboardBindingRead])
async def list_bindings(
    session: AsyncSession = Depends(get_session),
) -> list[DashboardBindingRead]:
    return [
        DashboardBindingRead.model_validate(b)
        for b in await store.list_dashboards(session)
    ]


@router.get("/{binding_id}", response_model=DashboardBindingRead)
async def get_binding(
    binding_id: int, session: AsyncSession = Depends(get_session)
) -> DashboardBindingRead:
    binding = await store.get_dashboard(session, binding_id)
    if binding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such dashboard binding.")
    return DashboardBindingRead.model_validate(binding)


@router.post("", response_model=DashboardBindingRead, status_code=201)
async def create_binding(
    payload: DashboardBindingCreate,
    session: AsyncSession = Depends(get_session),
) -> DashboardBindingRead:
    """Adopt an existing Superset dashboard."""
    binding = await store.create_dashboard_binding(
        session,
        name=payload.name,
        superset_dashboard_id=payload.superset_dashboard_id,
        embed_uuid=payload.embed_uuid,
        filter_id=payload.filter_id,
        auto_created=False,
    )
    return DashboardBindingRead.model_validate(binding)


@router.post("/blank", response_model=DashboardBindingRead, status_code=201)
async def create_blank(
    name: str = "New dashboard",
    session: AsyncSession = Depends(get_session),
) -> DashboardBindingRead:
    """Create a blank dashboard in Superset, wired for embedding and refresh.

    Degrades rather than failing: if Superset is unreachable the binding is
    still created, and Setup will show what is missing.
    """
    binding = await provisioning.provision_blank_dashboard(session, name=name)
    return DashboardBindingRead.model_validate(binding)


@router.patch("/{binding_id}", response_model=DashboardBindingRead)
async def update_binding(
    binding_id: int,
    payload: DashboardBindingUpdate,
    session: AsyncSession = Depends(get_session),
) -> DashboardBindingRead:
    binding = await store.get_dashboard(session, binding_id)
    if binding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such dashboard binding.")

    # Omitted means leave alone; "" clears.
    if payload.name is not None and payload.name:
        binding.name = payload.name
    if payload.superset_dashboard_id is not None:
        binding.superset_dashboard_id = payload.superset_dashboard_id or None
    if payload.embed_uuid is not None:
        binding.embed_uuid = payload.embed_uuid or None
    if payload.filter_id is not None:
        binding.filter_id = payload.filter_id or None

    await session.commit()
    await session.refresh(binding)
    return DashboardBindingRead.model_validate(binding)


@router.delete("/{binding_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_binding(
    binding_id: int,
    delete_in_superset: bool = False,
    session: AsyncSession = Depends(get_session),
) -> None:
    binding = await store.get_dashboard(session, binding_id)
    if binding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such dashboard binding.")

    # Only ever delete a dashboard this app created. Removing a binding must
    # not destroy someone's hand-built dashboard.
    if delete_in_superset and binding.auto_created and binding.superset_dashboard_id:
        try:
            async with httpx.AsyncClient(timeout=30.0) as http:
                await SupersetClient(http).delete_dashboard(
                    binding.superset_dashboard_id
                )
        except (SupersetError, SupersetUnreachable):
            # The local binding still goes away; a leftover dashboard in
            # Superset is harmless and visible there.
            pass

    await session.delete(binding)
    await session.commit()


@router.post("/{binding_id}/provision", response_model=DashboardBindingRead)
async def provision_missing(
    binding_id: int,
    session: AsyncSession = Depends(get_session),
) -> DashboardBindingRead:
    """Fill in whatever this binding is missing: dataset, refresh filter, embed.

    Used to recover a binding created while Superset was down.
    """
    binding = await store.get_dashboard(session, binding_id)
    if binding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such dashboard binding.")

    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=30.0) as http:
            client = SupersetClient(http)

            if not binding.superset_dashboard_id:
                binding.superset_dashboard_id = await client.create_dashboard(
                    binding.name
                )

            if not binding.filter_id:
                dataset_id = await client.ensure_dataset(
                    provisioning.SUBMISSIONS_TABLE, provisioning.SUPERSET_DATABASE_NAME
                )
                if dataset_id is not None:
                    binding.filter_id = await client.ensure_time_filter(
                        binding.superset_dashboard_id, dataset_id
                    )

            if not binding.embed_uuid:
                binding.embed_uuid = await client.enable_embedding(
                    binding.superset_dashboard_id, settings.cors_origin_list
                )
    except SupersetUnreachable as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"Could not reach Superset: {exc}"
        ) from exc
    except SupersetError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    await session.commit()
    await session.refresh(binding)
    return DashboardBindingRead.model_validate(binding)
