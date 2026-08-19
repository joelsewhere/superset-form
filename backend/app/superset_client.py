"""Thin client over Superset's REST API.

Everything the setup page needs to discover configuration rather than have it
typed in by hand: list dashboards, read or create a dashboard's embed config,
and enumerate its native filters.

Endpoints used (verified against the pinned Superset build):
  POST /api/v1/security/login
  GET  /api/v1/dashboard/
  POST /api/v1/dashboard/                        -> create a blank dashboard
  GET  /api/v1/dashboard/{id_or_slug}
  PUT  /api/v1/dashboard/{id}                    -> write json_metadata
  GET  /api/v1/dashboard/{id_or_slug}/embedded   -> {"result": {"uuid", ...}}
  POST /api/v1/dashboard/{id_or_slug}/embedded   -> {"result": {"uuid", ...}}
  GET  /api/v1/dataset/                          -> find the submissions dataset
  POST /api/v1/dataset/                          -> create it if absent
  GET  /api/v1/database/                         -> resolve the database id
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

# Refresh the admin token this many seconds before it expires, so a request in
# flight cannot land on a just-expired token.
_TOKEN_EXPIRY_MARGIN = 30.0
_DEFAULT_TOKEN_TTL = 300.0


class SupersetError(RuntimeError):
    """Superset was reachable but refused or failed the request."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class SupersetUnreachable(RuntimeError):
    """Superset could not be contacted at all."""


class SupersetClient:
    """One short-lived client per request. The access token is cached
    process-wide, since it is the expensive part."""

    _access_token: str | None = None
    _access_token_expires_at: float = 0.0

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client
        self._settings = get_settings()
        # CSRF is bound to the session cookie in THIS client's jar, so unlike
        # the access token it cannot be cached process-wide.
        self._csrf_token: str | None = None
        self._session_cookie: str | None = None

    @property
    def base_url(self) -> str:
        return self._settings.superset_url

    # -- auth ---------------------------------------------------------------

    async def _login(self) -> str:
        try:
            response = await self._client.post(
                f"{self.base_url}/api/v1/security/login",
                json={
                    "username": self._settings.superset_admin_username,
                    "password": self._settings.superset_admin_password,
                    "provider": "db",
                    "refresh": True,
                },
            )
        except httpx.HTTPError as exc:
            raise SupersetUnreachable(str(exc)) from exc

        if response.status_code != 200:
            raise SupersetError(
                f"Superset rejected the service account credentials "
                f"({response.status_code}).",
                response.status_code,
            )

        token = response.json()["access_token"]
        SupersetClient._access_token = token
        SupersetClient._access_token_expires_at = (
            time.monotonic() + _DEFAULT_TOKEN_TTL - _TOKEN_EXPIRY_MARGIN
        )
        return token

    async def access_token(self, force: bool = False) -> str:
        if (
            not force
            and SupersetClient._access_token
            and time.monotonic() < SupersetClient._access_token_expires_at
        ):
            return SupersetClient._access_token
        return await self._login()

    async def csrf_token(self, bearer: str) -> str | None:
        """Fetch a CSRF token, which Superset requires on mutating API calls.

        The token is tied to the session cookie Superset sets on this response,
        so the same httpx client (and therefore the same cookie jar) must be
        used for the follow-up request.
        """
        if self._csrf_token:
            return self._csrf_token

        try:
            response = await self._client.get(
                f"{self.base_url}/api/v1/security/csrf_token/",
                headers={"Authorization": f"Bearer {bearer}"},
            )
        except httpx.HTTPError as exc:
            raise SupersetUnreachable(str(exc)) from exc

        if response.status_code != 200:
            # Not fatal: a Superset with WTF_CSRF_ENABLED = False will not
            # serve this, and its mutating endpoints accept requests without it.
            logger.info(
                "CSRF token unavailable (%s); proceeding without one.",
                response.status_code,
            )
            return None

        self._csrf_token = response.json().get("result")

        # Superset ties the CSRF token to the session cookie set on this
        # response, and rejects the pair if either is missing.
        #
        # We read that cookie out of the jar and replay it as an explicit
        # header rather than letting httpx send it. superset_config sets
        # SESSION_COOKIE_SECURE = True (required so browsers accept the
        # SameSite=None cookie the in-page edit iframe depends on), and httpx
        # correctly refuses to send a Secure cookie over the plain-HTTP
        # internal network the backend uses to reach Superset. The cookie is
        # still *stored*, just not sent — so replaying it by hand is what lets
        # both the browser and this server-to-server path work at once.
        # Safe here: the traffic never leaves the compose network.
        self._session_cookie = self._client.cookies.get("session")
        return self._csrf_token

    async def request(
        self, method: str, path: str, **kwargs: Any
    ) -> httpx.Response:
        """Authenticated request, retrying once if a cached token is stale.

        Superset restarting invalidates tokens we still consider fresh, so a
        401 is retried with a newly minted one before being surfaced.
        """
        token = await self.access_token()
        mutating = method.upper() not in ("GET", "HEAD", "OPTIONS")

        async def _send(bearer: str) -> httpx.Response:
            headers = {"Authorization": f"Bearer {bearer}", **kwargs.pop("headers", {})}
            if mutating:
                csrf = await self.csrf_token(bearer)
                if csrf:
                    headers["X-CSRFToken"] = csrf
                    headers.setdefault("Referer", self.base_url)
                    if self._session_cookie:
                        headers["Cookie"] = f"session={self._session_cookie}"
            try:
                return await self._client.request(
                    method, f"{self.base_url}{path}", headers=headers, **kwargs
                )
            except httpx.HTTPError as exc:
                raise SupersetUnreachable(str(exc)) from exc

        response = await _send(token)
        if response.status_code == 401:
            logger.info("Cached Superset access token rejected; re-authenticating.")
            self._csrf_token = None
            self._session_cookie = None
            response = await _send(await self.access_token(force=True))
        return response

    # -- discovery ----------------------------------------------------------

    async def ping(self) -> dict[str, Any]:
        """Reachability plus whether our service account can authenticate."""
        try:
            health = await self._client.get(f"{self.base_url}/health")
        except httpx.HTTPError as exc:
            raise SupersetUnreachable(str(exc)) from exc

        result: dict[str, Any] = {
            "reachable": health.status_code == 200,
            "authenticated": False,
            "version": None,
        }

        await self.access_token(force=True)
        result["authenticated"] = True

        # Best-effort; a missing/!200 version endpoint is not an error worth
        # failing the whole ping over.
        try:
            me = await self.request("GET", "/api/v1/me/")
            if me.status_code == 200:
                result["username"] = me.json().get("result", {}).get("username")
        except (SupersetError, SupersetUnreachable):
            pass

        return result

    async def list_dashboards(self) -> list[dict[str, Any]]:
        query = json.dumps({"columns": ["id", "dashboard_title", "status"], "page_size": 100})
        response = await self.request("GET", f"/api/v1/dashboard/?q={query}")
        if response.status_code != 200:
            raise SupersetError(
                f"Could not list dashboards ({response.status_code}).",
                response.status_code,
            )
        return [
            {
                "id": str(item.get("id")),
                "title": item.get("dashboard_title") or f"Dashboard {item.get('id')}",
                "status": item.get("status"),
            }
            for item in response.json().get("result", [])
        ]

    async def get_embedded_uuid(self, dashboard_id: str) -> str | None:
        """The dashboard's embed UUID, or None if embedding is not enabled."""
        response = await self.request(
            "GET", f"/api/v1/dashboard/{dashboard_id}/embedded"
        )
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise SupersetError(
                f"Could not read the embed config ({response.status_code}).",
                response.status_code,
            )
        # Superset returns 200 with an empty result when embedding is off.
        result = response.json().get("result") or {}
        if isinstance(result, list):
            result = result[0] if result else {}
        return result.get("uuid") or None

    async def enable_embedding(
        self, dashboard_id: str, allowed_domains: list[str]
    ) -> str:
        """Turn embedding on (or update allowed domains) and return the UUID."""
        response = await self.request(
            "POST",
            f"/api/v1/dashboard/{dashboard_id}/embedded",
            json={"allowed_domains": allowed_domains},
        )
        if response.status_code not in (200, 201):
            raise SupersetError(
                f"Could not enable embedding ({response.status_code}): "
                f"{response.text[:200]}",
                response.status_code,
            )
        result = response.json().get("result") or {}
        uuid = result.get("uuid")
        if not uuid:
            raise SupersetError("Superset did not return an embed UUID.")
        return uuid

    async def list_native_filters(self, dashboard_id: str) -> list[dict[str, Any]]:
        """Native filters declared in the dashboard's JSON metadata.

        This is where the filter id the in-place refresh drives comes from —
        reading it here beats asking someone to dig it out of a URL.
        """
        response = await self.request("GET", f"/api/v1/dashboard/{dashboard_id}")
        if response.status_code != 200:
            raise SupersetError(
                f"Could not read the dashboard ({response.status_code}).",
                response.status_code,
            )

        result = response.json().get("result", {})
        raw_metadata = result.get("json_metadata")
        if not raw_metadata:
            return []

        try:
            metadata = json.loads(raw_metadata)
        except (TypeError, ValueError):
            logger.warning("Dashboard %s has unparseable json_metadata", dashboard_id)
            return []

        filters = []
        for item in metadata.get("native_filter_configuration", []) or []:
            filter_type = item.get("filterType") or ""
            targets = item.get("targets") or [{}]
            column = (targets[0] or {}).get("column", {}).get("name")
            filters.append(
                {
                    "id": item.get("id"),
                    "name": item.get("name") or item.get("id"),
                    "filter_type": filter_type,
                    "column": column,
                    # Surfaced so the UI can highlight the ones that make sense
                    # to drive, without hardcoding Superset's type constants.
                    "is_time": "time" in filter_type.lower(),
                }
            )
        return filters

    # -- provisioning -------------------------------------------------------

    async def create_dashboard(self, title: str) -> str:
        """Create a blank dashboard and return its numeric id."""
        response = await self.request(
            "POST",
            "/api/v1/dashboard/",
            json={"dashboard_title": title, "published": True},
        )
        if response.status_code not in (200, 201):
            raise SupersetError(
                f"Could not create the dashboard ({response.status_code}): "
                f"{response.text[:200]}",
                response.status_code,
            )
        return str(response.json()["id"])

    async def delete_dashboard(self, dashboard_id: str) -> None:
        response = await self.request("DELETE", f"/api/v1/dashboard/{dashboard_id}")
        if response.status_code not in (200, 404):
            raise SupersetError(
                f"Could not delete the dashboard ({response.status_code}).",
                response.status_code,
            )

    async def get_database_id(self, name: str) -> int | None:
        query = json.dumps({"filters": [{"col": "database_name", "opr": "eq", "value": name}]})
        response = await self.request("GET", f"/api/v1/database/?q={query}")
        if response.status_code != 200:
            return None
        results = response.json().get("result", [])
        return results[0]["id"] if results else None

    async def find_dataset_id(self, table_name: str) -> int | None:
        query = json.dumps(
            {"filters": [{"col": "table_name", "opr": "eq", "value": table_name}]}
        )
        response = await self.request("GET", f"/api/v1/dataset/?q={query}")
        if response.status_code != 200:
            return None
        results = response.json().get("result", [])
        return results[0]["id"] if results else None

    async def create_dataset(
        self, database_id: int, table_name: str, schema: str = "public"
    ) -> int:
        response = await self.request(
            "POST",
            "/api/v1/dataset/",
            json={
                "database": database_id,
                "schema": schema,
                "table_name": table_name,
            },
        )
        if response.status_code not in (200, 201):
            raise SupersetError(
                f"Could not create the dataset ({response.status_code}): "
                f"{response.text[:200]}",
                response.status_code,
            )
        return int(response.json()["id"])

    async def ensure_dataset(
        self, table_name: str, database_name: str, schema: str = "public"
    ) -> int | None:
        """Find the dataset, creating it if Superset does not have it yet."""
        existing = await self.find_dataset_id(table_name)
        if existing is not None:
            return existing

        database_id = await self.get_database_id(database_name)
        if database_id is None:
            logger.warning(
                "Database %r is not registered in Superset; cannot create the "
                "%r dataset automatically.",
                database_name,
                table_name,
            )
            return None
        return await self.create_dataset(database_id, table_name, schema)

    async def set_json_metadata(self, dashboard_id: str, metadata: dict) -> None:
        response = await self.request(
            "PUT",
            f"/api/v1/dashboard/{dashboard_id}",
            json={"json_metadata": json.dumps(metadata)},
        )
        if response.status_code not in (200, 201):
            raise SupersetError(
                f"Could not write the dashboard metadata ({response.status_code}): "
                f"{response.text[:200]}",
                response.status_code,
            )

    async def get_json_metadata(self, dashboard_id: str) -> dict:
        response = await self.request("GET", f"/api/v1/dashboard/{dashboard_id}")
        if response.status_code != 200:
            raise SupersetError(
                f"Could not read the dashboard ({response.status_code}).",
                response.status_code,
            )
        raw = response.json().get("result", {}).get("json_metadata")
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return {}

    async def ensure_time_filter(
        self,
        dashboard_id: str,
        dataset_id: int,
        column: str = "created_at",
        name: str = "Live refresh",
    ) -> str | None:
        """Add a time-range native filter on `column`, unless one already exists.

        This is the filter the in-place refresh drives. Creating it here is what
        lets an auto-provisioned dashboard support live updates with no manual
        setup in Superset.
        """
        metadata = await self.get_json_metadata(dashboard_id)
        existing = metadata.get("native_filter_configuration") or []

        for item in existing:
            targets = item.get("targets") or [{}]
            target_column = (targets[0] or {}).get("column", {}).get("name")
            if "time" in (item.get("filterType") or "").lower() and target_column == column:
                return item.get("id")

        filter_id = f"NATIVE_FILTER-{uuid.uuid4().hex[:12]}"
        existing.append(
            {
                "id": filter_id,
                "name": name,
                "filterType": "filter_time",
                "type": "NATIVE_FILTER",
                "targets": [{"datasetId": dataset_id, "column": {"name": column}}],
                "defaultDataMask": {"extraFormData": {}, "filterState": {}, "ownState": {}},
                "controlValues": {},
                "scope": {"rootPath": ["ROOT_ID"], "excluded": []},
                # Applies to every chart on the dashboard; a filter scoped to a
                # subset would leave some charts stale after a submission.
                "chartsInScope": [],
                "tabsInScope": [],
                "description": "Driven by FrontFlow to refresh charts in place.",
            }
        )
        metadata["native_filter_configuration"] = existing
        await self.set_json_metadata(dashboard_id, metadata)
        return filter_id
