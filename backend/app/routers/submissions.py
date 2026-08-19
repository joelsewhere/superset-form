"""Form submission capture.

The validation model is generated from the form the submission names, not from
a model fixed at import time — that is what lets an external form builder
change a form without a deploy.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import store
from app.db import get_session
from app.form_schema import build_submission_model
from app.models import Submission
from app.routers.forms import column_names
from app.schemas import SubmissionRead

router = APIRouter(prefix="/api", tags=["submissions"])

# Columns that must be present for a row to be insertable at all.
REQUIRED_COLUMNS = ("region", "product", "units", "unit_price", "sale_date")

# Building a pydantic model is not free, so cache per form version. Keyed on
# the form's id and updated_at, both of which change on write.
_model_cache: dict[tuple[int, str], Any] = {}


async def _model_for(session: AsyncSession, form_id: int):
    form = await store.get_form(session, form_id)
    if form is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such form.")

    key = (form.id, str(form.updated_at))
    if key not in _model_cache:
        # Bound cache: only current versions matter, and forms are few.
        if len(_model_cache) > 64:
            _model_cache.clear()
        _model_cache[key] = build_submission_model(store.form_fields(form))
    return form, _model_cache[key]


@router.post(
    "/forms/{form_id}/submissions",
    response_model=SubmissionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_submission(
    form_id: int,
    body: dict[str, Any],
    session: AsyncSession = Depends(get_session),
) -> Submission:
    form, model = await _model_for(session, form_id)

    try:
        validated = model(**body)
    except ValidationError as exc:
        raise HTTPException(
            # Numeric rather than the named constant: Starlette renamed
            # HTTP_422_UNPROCESSABLE_ENTITY, and the int works on both.
            status_code=422,
            detail=exc.errors(include_url=False),
        ) from exc

    data = validated.model_dump()
    # Enum-typed select fields serialise to their string value.
    data = {k: (v.value if hasattr(v, "value") else v) for k, v in data.items()}

    columns = column_names()
    mapped = {k: v for k, v in data.items() if k in columns}
    payload = {k: v for k, v in data.items() if k not in columns}

    missing = [c for c in REQUIRED_COLUMNS if c not in mapped]
    if missing:
        # The form has drifted from the table's NOT NULL columns. Fail loudly
        # here rather than with an opaque IntegrityError.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Form {form.name!r} does not supply required columns: "
                f"{', '.join(missing)}. Either add these fields to the form or "
                "migrate the submissions table."
            ),
        )

    submission = Submission(**mapped, payload=payload, form_definition_id=form.id)
    session.add(submission)
    await session.commit()
    await session.refresh(submission)
    return submission


@router.get("/forms/{form_id}/submissions", response_model=list[SubmissionRead])
async def list_form_submissions(
    form_id: int,
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[Submission]:
    result = await session.execute(
        select(Submission)
        .where(Submission.form_definition_id == form_id)
        .order_by(Submission.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


@router.get("/submissions", response_model=list[SubmissionRead])
async def list_submissions(
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[Submission]:
    result = await session.execute(
        select(Submission)
        .order_by(Submission.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())
