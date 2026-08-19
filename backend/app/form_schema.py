"""Form field definitions and the validation model derived from them.

The ACTIVE definition lives in the database (`form_definitions`), so an
external form builder can replace it over `PUT /api/form-schema` without a
deploy. DEFAULT_FIELDS below is only the seed used on first startup.

Whatever the active definition is, the API's validation model is generated
from it, so validation can never drift from the rendered form.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, create_model

FieldType = Literal["text", "textarea", "number", "select", "date"]


class FormField(BaseModel):
    """Declarative description of one input, serialised to the frontend."""

    name: str
    label: str
    type: FieldType
    required: bool = True
    help_text: str | None = None
    options: list[str] | None = None
    min: float | None = None
    max: float | None = None
    step: float | None = None
    placeholder: str | None = None


REGIONS = ["North", "South", "East", "West", "Central"]
PRODUCTS = ["Widget", "Gadget", "Doohickey", "Gizmo"]

DEFAULT_FIELDS: list[FormField] = [
    FormField(
        name="region",
        label="Region",
        type="select",
        options=REGIONS,
        help_text="Sales territory the order belongs to.",
    ),
    FormField(
        name="product",
        label="Product",
        type="select",
        options=PRODUCTS,
    ),
    FormField(
        name="units",
        label="Units",
        type="number",
        min=1,
        max=100_000,
        step=1,
        placeholder="0",
    ),
    FormField(
        name="unit_price",
        label="Unit price",
        type="number",
        min=0,
        step=0.01,
        placeholder="0.00",
        help_text="Price per unit, before discount.",
    ),
    FormField(
        name="sale_date",
        label="Sale date",
        type="date",
    ),
    FormField(
        name="notes",
        label="Notes",
        type="textarea",
        required=False,
        placeholder="Optional context for this entry",
    ),
]

_PYTHON_TYPES: dict[str, Any] = {
    "text": str,
    "textarea": str,
    "number": float,
    "date": date,
}


def _annotation_for(field: FormField) -> Any:
    if field.type == "select" and field.options:
        # A closed set of options becomes a real enum, so an out-of-range
        # value is a 422 rather than a surprise row in the dashboard.
        return Enum(  # type: ignore[return-value]
            f"{field.name.title().replace('_', '')}Enum",
            {opt.upper().replace(" ", "_"): opt for opt in field.options},
            type=str,
        )
    return _PYTHON_TYPES[field.type]


def build_submission_model(fields: list[FormField]) -> type[BaseModel]:
    """Construct a request model from an arbitrary field definition."""
    definitions: dict[str, tuple[Any, Any]] = {}

    for field in fields:
        annotation = _annotation_for(field)
        constraints: dict[str, Any] = {}
        if field.type == "number":
            if field.min is not None:
                constraints["ge"] = field.min
            if field.max is not None:
                constraints["le"] = field.max

        if field.required:
            definitions[field.name] = (annotation, Field(..., **constraints))
        else:
            definitions[field.name] = (annotation | None, Field(None, **constraints))

    return create_model("SubmissionCreate", **definitions)  # type: ignore[call-overload]
