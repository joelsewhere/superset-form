"""Auto-provisioning of Superset resources.

When a form arrives with no dashboard attached, this creates one: a blank
Superset dashboard, the `v_submissions` dataset if Superset does not have it
yet, a time-range native filter on `created_at` so live refresh works out of
the box, and the embed configuration.

Every step degrades rather than failing the caller. A form that could not be
given a dashboard is still a usable form — the Setup panel will show what is
missing and let it be fixed by hand.
"""

from __future__ import annotations

import logging

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app import store
from app.config import get_settings
from app.models import DashboardBinding, FormDefinition
from app.superset_client import SupersetClient, SupersetError, SupersetUnreachable

logger = logging.getLogger(__name__)

SUBMISSIONS_TABLE = "v_submissions"
SUPERSET_DATABASE_NAME = "FrontFlow"


async def provision_blank_dashboard(
    session: AsyncSession,
    *,
    name: str,
    allowed_domains: list[str] | None = None,
) -> DashboardBinding:
    """Create a blank Superset dashboard and return a binding for it.

    The binding is persisted even if Superset is unreachable, so the app has a
    stable reference; the missing pieces can be filled in later from Setup.
    """
    settings = get_settings()
    domains = allowed_domains or settings.cors_origin_list

    superset_dashboard_id: str | None = None
    embed_uuid: str | None = None
    filter_id: str | None = None

    try:
        async with httpx.AsyncClient(timeout=30.0) as http:
            client = SupersetClient(http)

            superset_dashboard_id = await client.create_dashboard(name)

            # The filter needs a dataset to target. Absent one, the dashboard
            # is still created and embeddable — just without live refresh.
            dataset_id = await client.ensure_dataset(
                SUBMISSIONS_TABLE, SUPERSET_DATABASE_NAME
            )
            if dataset_id is not None:
                filter_id = await client.ensure_time_filter(
                    superset_dashboard_id, dataset_id
                )
            else:
                logger.warning(
                    "No %s dataset in Superset; dashboard %s created without a "
                    "refresh filter.",
                    SUBMISSIONS_TABLE,
                    superset_dashboard_id,
                )

            embed_uuid = await client.enable_embedding(superset_dashboard_id, domains)

    except (SupersetError, SupersetUnreachable) as exc:
        logger.warning("Could not fully provision dashboard %r: %s", name, exc)

    return await store.create_dashboard_binding(
        session,
        name=name,
        superset_dashboard_id=superset_dashboard_id,
        embed_uuid=embed_uuid,
        filter_id=filter_id,
        auto_created=True,
    )


async def ensure_form_has_dashboard(
    session: AsyncSession, form: FormDefinition
) -> DashboardBinding | None:
    """Give a form a blank dashboard if it has none linked yet."""
    if form.dashboards:
        return form.dashboards[0]

    binding = await provision_blank_dashboard(session, name=f"{form.name} — dashboard")
    await store.link_form_dashboard(session, form, binding)
    await session.refresh(form)
    return binding
