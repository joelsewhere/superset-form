"""FastAPI application entrypoint."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import dashboards, forms, setup, submissions, superset, views

logging.basicConfig(level=logging.INFO)


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="FrontFlow BI",
        description=(
            "Views composed of form and dashboard panels, with live Superset "
            "embedding."
        ),
        version="0.2.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(views.router)
    app.include_router(forms.router)
    app.include_router(dashboards.router)
    app.include_router(submissions.router)
    app.include_router(setup.router)
    app.include_router(superset.router)

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
