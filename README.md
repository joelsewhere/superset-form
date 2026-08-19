# FrontFlow BI

A split-screen webtool that closes the loop between data entry and data
visualisation on one screen: fill in the form on one side, watch the Superset
dashboard on the other side move in response.

Both panels are freely dockable — drag a tab to any edge to re-dock it, drag it
onto another tab strip to make a tabbed group, and double-click a tab to
collapse that panel to a spine.

```
┌───────────────────┬───────────────────────────────┐
│  New submission   │  Dashboard                    │
│                   │                               │
│  [ Region     ▾ ] │   ┌────────┐  ┌────────────┐  │
│  [ Product    ▾ ] │   │ revenue│  │ units/day  │  │
│  [ Units        ] │   └────────┘  └────────────┘  │
│  [ Unit price   ] │   ┌──────────────────────────┐│
│  [ Sale date    ] │   │  by region               ││
│  [ Notes        ] │   └──────────────────────────┘│
│  ( Submit )       │                               │
│  ── recent ────── │                               │
└───────────────────┴───────────────────────────────┘
      drag either tab to any edge to re-dock
```

## Stack

| Piece | What it is |
|---|---|
| `frontend` | React 18 + TypeScript + Vite, [dockview](https://dockview.dev) for the dock layout, `@superset-ui/embedded-sdk` for the embed |
| `backend` | FastAPI — captures submissions, serves the form schema, mints Superset guest tokens |
| `postgres` | One container, two databases: `superset` (Superset's own metadata) and `frontflow` (application data) |
| `superset` | Apache Superset, pinned to master build `5ce52e5` — see [How the refresh works](#how-the-refresh-works) |
| `redis` | Superset's cache |

Superset reads application data through a dedicated `superset_ro` role with
`SELECT`-only grants. It can never write to the application's tables.

## Quick start

```bash
cp .env.example .env
# Fill in the secrets. Nothing about the dashboard binding goes here — that is
# configured from the app's Setup panel and stored in the database.

docker compose up -d
docker compose ps          # all six services should be healthy
```

| Service | URL |
|---|---|
| App | http://localhost:5173 |
| Backend docs | http://localhost:8000/docs |
| Superset | http://localhost:8088 |

The form works immediately. The dashboard panel shows a message pointing at the
Setup panel until a dashboard is bound.

## Setup

Open the app and use the **Setup** panel (a tab next to the form). It discovers
the configuration rather than making you copy values by hand:

1. **Superset connection** — pings Superset and confirms the service account can
   authenticate. Retries on its own while the container is still starting.
2. **Dashboard** — lists the dashboards Superset has.
3. **Embedding** — shows whether embedding is on for the selected dashboard, and
   enables it with one button if not, reading the embed UUID straight back from
   the API.
4. **Refresh filter** — lists the dashboard's native filters and lets you pick
   the one the live refresh drives. Time-range filters are labelled as such.
5. **Save** — persists the binding to the database. It takes effect immediately;
   no `.env` edit and no restart.

The only part that still has to happen in Superset's own UI is creating the
dataset, the charts, and the filter:

1. Log in to http://localhost:8088 with `SUPERSET_ADMIN_USERNAME` /
   `SUPERSET_ADMIN_PASSWORD`.

2. **Confirm the database connection.** Under *Settings → Database Connections*
   there should be one named `FrontFlow`. If the bootstrap could not create it,
   add it manually with:
   ```
   postgresql://superset_ro:<SUPERSET_RO_PASSWORD>@postgres:5432/frontflow
   ```

3. **Create the dataset.** *Datasets → + Dataset*, database `FrontFlow`, schema
   `public`, table **`v_submissions`**.

   Use the view, not the `submissions` table. The view exposes a computed
   `revenue` column so every chart agrees on its definition, and it lets the
   physical schema change later without breaking saved charts.

4. **Build the dashboard.** Any charts you like over `v_submissions`.

5. **Add a native time-range filter** on `created_at`, scoped to **all charts**.
   This is what the app drives to refresh the dashboard; the Setup panel will
   find it automatically.

6. **Set a backstop refresh interval.** *Edit properties → Advanced → JSON
   metadata*:
   ```json
   { "refresh_frequency": 30 }
   ```
   Submissions in this browser tab update instantly via the filter. This
   interval only covers writes made by *other* users.

Then return to the Setup panel and work through steps 2–5 there.

## How the refresh works

Submitting the form updates the dashboard **in place, within about a second**.
The iframe is never remounted, so there is no flash.

The mechanism: the dashboard carries a native time-range filter on
`created_at`, and on each submission the app pushes a new upper bound of "now"
through the SDK's `setDataMask`. That dispatches `updateDataMask` into the
dashboard's Redux store — exactly the code path a user clicking a filter takes
— so the charts re-query inside the existing iframe. Because the filter value
participates in the query cache key, each submit produces a genuinely fresh
result rather than a cached one.

### Why the SDK is vendored and the image is pinned to a commit

`setDataMask` is **unreleased on both sides**:

- `@superset-ui/embedded-sdk@0.4.0`, the latest published SDK, does not expose
  it anywhere in its types or its bundle.
- Superset **4.1.1 and 5.0.0** register only `getActiveTabs` and
  `getScrollSize` on the embedded switchboard.

So this project runs two matched, unreleased pins:

| Piece | Pin |
|---|---|
| Superset image | `apache/superset:5ce52e5` |
| Embedded SDK | vendored at `frontend/src/vendor/superset-embedded-sdk`, same commit |

**These must be bumped together.** The host SDK and the embedded page speak the
same switchboard protocol, and this feature exists only in unreleased builds of
both. See `frontend/src/vendor/superset-embedded-sdk/README.md`.

Running an unreleased Superset build is a deliberate trade for the instant
loop. If that is not acceptable for your deployment, the fallback is to pin
both back to a release and rely on the dashboard's `refresh_frequency` alone —
also flash-free, but on a timer rather than instant.

A mismatch is at least loud rather than silent: `setDataMask` is sent with
`port.get`, so an embedded page that predates it replies with an error. The
panel surfaces that as a "Live refresh unavailable" banner instead of appearing
to work.

### A trap to know about

SDK 0.4.0 *declares* `getChartStates`, `getDataMask`, and `observeDataMask` in
its TypeScript types even though no released Superset implements them. Calls to
those typecheck cleanly and then hang. If you ever revert to the published SDK,
do not assume a declared method is an implemented one.

## Connecting a form builder

The form's fields are **not** hardcoded. They live in the database and are
replaced over one endpoint, so an external form builder can drive what this app
renders and validates without a deploy or a migration.

### The contract

```
GET  /api/form-schema      -> FormField[]          (what the app renders today)
PUT  /api/form-schema      <- { name, fields[] }   (replace it)
GET  /api/form-definition  -> definition + storage mapping
```

A `FormField` is:

```jsonc
{
  "name": "sales_rep",        // required; also the storage key
  "label": "Sales rep",       // required
  "type": "text",             // text | textarea | number | select | date
  "required": true,
  "help_text": null,
  "options": null,            // required for type "select"
  "min": null, "max": null, "step": null,   // numbers only
  "placeholder": null
}
```

Pushing a definition:

```bash
curl -X PUT http://localhost:8000/api/form-schema \
  -H 'Content-Type: application/json' \
  -d '{
        "name": "my-builder-form",
        "fields": [
          {"name":"region","label":"Region","type":"select",
           "required":true,"options":["North","South"]},
          {"name":"sales_rep","label":"Sales rep","type":"text","required":true}
        ]
      }'
```

That single call changes, together and atomically:

- what the form panel renders,
- the client-side validators (generated from the same definition), and
- the server-side validation model (likewise), so a value the form rejects is
  also rejected by the API.

There is no separate schema to keep in sync — that is the point of the seam.

### Where fields are stored

Field names that match a `submissions` column go into that column. Everything
else goes into the JSONB `payload` column, so **new fields need no migration**.
`PUT` and `GET /api/form-definition` both return the split, so a builder can see
the consequences of a definition before relying on it:

```json
{
  "mapped_columns": ["region", "product", "units", "unit_price", "sale_date"],
  "payload_fields": ["sales_rep", "channel"]
}
```

Both are visible in the Setup panel's "Form definition" section.

`payload` is exposed by the `v_submissions` view, so payload fields are
queryable from Superset — for example `payload->>'sales_rep'` as a calculated
column on the dataset.

### The one constraint

`submissions` has NOT NULL columns (`region`, `product`, `units`, `unit_price`,
`sale_date`) inherited from the seed schema. A definition that drops one of them
is rejected at submit time with a `409` naming the missing columns, rather than
failing with an opaque database error.

If your builder's forms have a genuinely different shape, either add a migration
that relaxes those columns, or narrow the typed columns to whatever is truly
common and let the rest live in `payload`. The check that enforces this is in
`backend/app/routers/submissions.py`.

### Seeding

`backend/app/form_schema.py::DEFAULT_FIELDS` is only the seed used on first
startup, when no definition exists yet. Once a builder has pushed one, that file
is no longer consulted.

## Security notes

This is a local development stack. Before deploying anything:

- **`POST /api/superset/guest-token` is unauthenticated.** As written it mints a
  dashboard token for anyone who can reach it. Put the application's own auth in
  front of it, pass the authenticated user through to the `user` field, and
  populate `rls` for row-level security.
- **`TALISMAN_ENABLED = False`** in `superset/superset_config.py` disables the
  CSP that would otherwise block the iframe. In production, keep Talisman on and
  pin `frame-ancestors` to the app's origin instead. There is a worked example
  in the config file's comments.
- Every credential in `.env.example` is a placeholder. Replace all of them.

## Troubleshooting

| Symptom | Cause |
|---|---|
| Dashboard panel says no dashboard is configured | Nothing bound yet — use the Setup panel |
| Iframe blank, no error | Embed UUID is wrong — re-run *Enable embedding* in the Setup panel |
| Iframe blocked, console shows `frame-ancestors` | Talisman CSP — `TALISMAN_ENABLED` must be `False` locally |
| Iframe loads, every chart errors | CORS — check `CORS_ALLOWED_ORIGIN` matches the frontend's origin exactly |
| Guest token 502 / 503 | Backend cannot reach Superset, or admin credentials are wrong — the Setup panel's step 1 says which |
| New rows never appear | No refresh filter picked in Setup, or the dashboard's time-range filter is not scoped to all charts |
| Submitted a field the form defines but nothing stored it | Check `payload_fields` in Setup — it may be landing in `payload` rather than a column |
| "Live refresh unavailable" banner | Superset image pin does not match the vendored SDK — both must be on the same commit |
| Blank screen after an upgrade | Stale persisted layout — click *Reset layout* in a panel header, or clear `frontflow.layout.v2` from localStorage |

## Development without Docker

```bash
# backend
cd backend && pip install -e . && alembic upgrade head
uvicorn app.main:app --reload

# frontend
cd frontend && npm install && npm run dev
```

Both expect the environment variables from `.env`.
