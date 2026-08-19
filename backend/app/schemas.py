"""Request and response models."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.form_schema import FormField


# --- submissions -----------------------------------------------------------


class SubmissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    form_definition_id: int | None
    region: str
    product: str
    units: float
    unit_price: float
    sale_date: date
    notes: str | None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


# --- dashboards ------------------------------------------------------------


class DashboardBindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    superset_dashboard_id: str | None
    embed_uuid: str | None
    filter_id: str | None
    auto_created: bool
    updated_at: datetime | None = None


class DashboardBindingCreate(BaseModel):
    name: str = Field(max_length=255)
    superset_dashboard_id: str | None = None
    embed_uuid: str | None = None
    filter_id: str | None = None


class DashboardBindingUpdate(BaseModel):
    """Omitted means "leave alone"; "" clears."""

    name: str | None = None
    superset_dashboard_id: str | None = None
    embed_uuid: str | None = None
    filter_id: str | None = None


# --- forms -----------------------------------------------------------------


class FormSummary(BaseModel):
    id: int
    name: str
    field_count: int
    dashboard_ids: list[int]


class FormRead(BaseModel):
    id: int
    name: str
    fields: list[FormField]
    dashboard_ids: list[int]
    updated_at: datetime | None = None
    # Which fields have a dedicated column and which land in payload, so a
    # form builder can see how its definition will be stored.
    mapped_columns: list[str] = Field(default_factory=list)
    payload_fields: list[str] = Field(default_factory=list)


class FormWrite(BaseModel):
    """Payload an external form builder PUTs to create or replace a form."""

    name: str = Field(max_length=128)
    fields: list[FormField] = Field(min_length=1)
    # When true (the default) a form arriving with no dashboard gets a blank
    # one created and linked automatically.
    provision_dashboard: bool = True


# --- views -----------------------------------------------------------------


class PanelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    panel_key: str
    kind: Literal["form", "dashboard"]
    title: str | None
    position: int
    form_definition_id: int | None
    dashboard_binding_id: int | None


class PanelCreate(BaseModel):
    kind: Literal["form", "dashboard"]
    form_definition_id: int | None = None
    dashboard_binding_id: int | None = None
    title: str | None = None


class ViewSummary(BaseModel):
    id: int
    name: str
    is_default: bool
    panel_count: int


class ViewRead(BaseModel):
    id: int
    name: str
    is_default: bool
    layout: dict[str, Any] | None
    panels: list[PanelRead]


class ViewCreate(BaseModel):
    name: str = Field(max_length=255)
    is_default: bool = False


class ViewLayoutUpdate(BaseModel):
    layout: dict[str, Any] | None = None


# --- Superset discovery ----------------------------------------------------


class GuestTokenResponse(BaseModel):
    token: str


class SupersetStatus(BaseModel):
    reachable: bool
    authenticated: bool
    username: str | None = None
    url: str
    detail: str | None = None


class SupersetDashboard(BaseModel):
    id: str
    title: str
    status: str | None = None


class SupersetNativeFilter(BaseModel):
    id: str
    name: str
    filter_type: str
    column: str | None = None
    is_time: bool = False


class EnableEmbeddingRequest(BaseModel):
    allowed_domains: list[str] = Field(default_factory=list)
