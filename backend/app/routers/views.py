"""Views: saved workspaces holding any number of form and dashboard panels."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import provisioning, store
from app.db import get_session
from app.models import View
from app.schemas import (
    PanelCreate,
    PanelRead,
    ViewCreate,
    ViewLayoutUpdate,
    ViewRead,
    ViewSummary,
)

router = APIRouter(prefix="/api/views", tags=["views"])


def to_read(view: View) -> ViewRead:
    return ViewRead(
        id=view.id,
        name=view.name,
        is_default=view.is_default,
        layout=view.layout,
        panels=[PanelRead.model_validate(p) for p in view.panels],
    )


@router.get("", response_model=list[ViewSummary])
async def list_views(session: AsyncSession = Depends(get_session)) -> list[ViewSummary]:
    views = await store.list_views(session)
    if not views:
        # Bootstrap on first access so the app always has something to open.
        await bootstrap_default(session)
        views = await store.list_views(session)

    return [
        ViewSummary(
            id=v.id, name=v.name, is_default=v.is_default, panel_count=len(v.panels)
        )
        for v in views
    ]


@router.get("/default", response_model=ViewRead)
async def get_default_view(session: AsyncSession = Depends(get_session)) -> ViewRead:
    view = await store.get_default_view(session)
    if view is None:
        view = await bootstrap_default(session)
    return to_read(view)


@router.get("/{view_id}", response_model=ViewRead)
async def get_view(
    view_id: int, session: AsyncSession = Depends(get_session)
) -> ViewRead:
    view = await store.get_view(session, view_id)
    if view is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such view.")
    return to_read(view)


@router.post("", response_model=ViewRead, status_code=status.HTTP_201_CREATED)
async def create_view(
    payload: ViewCreate, session: AsyncSession = Depends(get_session)
) -> ViewRead:
    view = await store.create_view(
        session, name=payload.name, is_default=payload.is_default
    )
    return to_read(view)


@router.put("/{view_id}/layout", response_model=ViewRead)
async def update_layout(
    view_id: int,
    payload: ViewLayoutUpdate,
    session: AsyncSession = Depends(get_session),
) -> ViewRead:
    """Persist the dock arrangement. Called on every layout change (debounced
    client-side), so it is deliberately cheap — a single JSON column write."""
    view = await store.get_view(session, view_id)
    if view is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such view.")

    view.layout = payload.layout
    await session.commit()
    await session.refresh(view)
    return to_read(view)


@router.post("/{view_id}/panels", response_model=ViewRead)
async def add_panel(
    view_id: int,
    payload: PanelCreate,
    session: AsyncSession = Depends(get_session),
) -> ViewRead:
    view = await store.get_view(session, view_id)
    if view is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such view.")

    if payload.kind == "form":
        if payload.form_definition_id is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "A form panel needs form_definition_id."
            )
        form = await store.get_form(session, payload.form_definition_id)
        if form is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such form.")
        title = payload.title or form.name
    else:
        if payload.dashboard_binding_id is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "A dashboard panel needs dashboard_binding_id.",
            )
        binding = await store.get_dashboard(session, payload.dashboard_binding_id)
        if binding is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such dashboard.")
        title = payload.title or binding.name

    await store.add_panel(
        session,
        view,
        kind=payload.kind,
        form_definition_id=payload.form_definition_id,
        dashboard_binding_id=payload.dashboard_binding_id,
        title=title,
    )
    await session.refresh(view)
    return to_read(view)


@router.delete("/{view_id}/panels/{panel_id}", response_model=ViewRead)
async def remove_panel(
    view_id: int,
    panel_id: int,
    session: AsyncSession = Depends(get_session),
) -> ViewRead:
    view = await store.get_view(session, view_id)
    if view is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such view.")

    panel = next((p for p in view.panels if p.id == panel_id), None)
    if panel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such panel in this view.")

    await session.delete(panel)
    await session.commit()
    await session.refresh(view)
    return to_read(view)


async def bootstrap_default(session: AsyncSession) -> View:
    """First-run setup: a seed form with its own blank dashboard, in a default
    view showing both side by side."""
    view = await store.ensure_default_view(session)
    if view.panels:
        return view

    form = await store.ensure_seed_form(session)
    binding = await provisioning.ensure_form_has_dashboard(session, form)

    await store.add_panel(
        session, view, kind="form", form_definition_id=form.id, title=form.name
    )
    if binding is not None:
        await store.add_panel(
            session,
            view,
            kind="dashboard",
            dashboard_binding_id=binding.id,
            title=binding.name,
        )

    await session.refresh(view)
    return view
