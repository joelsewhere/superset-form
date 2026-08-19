import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import type { DashboardBinding, FormSummary, SupersetNativeFilter } from '../api/client'
import { useActiveViewId } from '../layout/ViewContext'

/**
 * Setup: manage dashboards, forms, and what this view shows.
 *
 * Configuration is discovered from Superset's API rather than typed in — the
 * embed UUID is read from (or created via) the embed endpoint, and filter ids
 * come from the dashboard's own metadata.
 */
export function SetupPanel() {
  return (
    <div className="ff-panel ff-panel--setup">
      <ConnectionSection />
      <DashboardsSection />
      <FormsSection />
      <ThisViewSection />
    </div>
  )
}

// --- 1. connection ---------------------------------------------------------

function ConnectionSection() {
  const status = useQuery({
    queryKey: ['superset-status'],
    queryFn: api.getSupersetStatus,
    // Poll while Superset is down so the panel recovers on its own once the
    // container finishes starting; stop once it is up.
    refetchInterval: (query) => (query.state.data?.authenticated ? false : 5000),
  })

  return (
    <Section title="Superset connection">
      {status.isPending ? (
        <p className="ff-muted">Checking…</p>
      ) : status.data?.authenticated ? (
        <p className="ff-status ff-status--ok">
          Connected to {status.data.url}
          {status.data.username ? ` as ${status.data.username}` : ''}
        </p>
      ) : (
        <>
          <p className="ff-status ff-status--bad">
            {status.data?.reachable
              ? 'Reachable, but the service account could not authenticate.'
              : 'Not reachable.'}
          </p>
          {status.data?.detail && <p className="ff-muted ff-small">{status.data.detail}</p>}
          <p className="ff-muted ff-small">Retrying automatically…</p>
        </>
      )}
    </Section>
  )
}

// --- 2. dashboards ---------------------------------------------------------

function DashboardsSection() {
  const queryClient = useQueryClient()
  const [adopting, setAdopting] = useState(false)

  const dashboards = useQuery({ queryKey: ['dashboards'], queryFn: api.listDashboards })

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['dashboards'] })
    queryClient.invalidateQueries({ queryKey: ['forms'] })
  }

  const createBlank = useMutation({
    mutationFn: () => api.createBlankDashboard('New dashboard'),
    onSuccess: invalidate,
  })

  return (
    <Section title="Dashboards">
      <p className="ff-muted ff-small">
        A blank dashboard is created and wired for live refresh automatically.
        Adopt an existing one to point a form at something you already built.
      </p>

      {dashboards.isPending && <p className="ff-muted">Loading…</p>}
      {dashboards.error && <p className="ff-error-banner">{dashboards.error.message}</p>}

      <ul className="ff-list">
        {dashboards.data?.map((binding) => (
          <DashboardRow key={binding.id} binding={binding} onChanged={invalidate} />
        ))}
      </ul>

      <div className="ff-button-row">
        <button
          type="button"
          className="ff-button ff-button--small"
          onClick={() => createBlank.mutate()}
          disabled={createBlank.isPending}
        >
          {createBlank.isPending ? 'Creating…' : '+ Blank dashboard'}
        </button>
        <button
          type="button"
          className="ff-button ff-button--ghost ff-button--small"
          onClick={() => setAdopting((v) => !v)}
        >
          {adopting ? 'Cancel' : 'Adopt existing'}
        </button>
      </div>

      {createBlank.isError && (
        <p className="ff-error-banner">{createBlank.error.message}</p>
      )}
      {adopting && (
        <AdoptExisting
          onDone={() => {
            setAdopting(false)
            invalidate()
          }}
        />
      )}
    </Section>
  )
}

function DashboardRow({
  binding,
  onChanged,
}: {
  binding: DashboardBinding
  onChanged: () => void
}) {
  const [expanded, setExpanded] = useState(false)

  const repair = useMutation({
    mutationFn: () => api.repairDashboard(binding.id),
    onSuccess: onChanged,
  })
  const remove = useMutation({
    mutationFn: () => api.deleteDashboard(binding.id, binding.auto_created),
    onSuccess: onChanged,
  })
  const setFilter = useMutation({
    mutationFn: (filterId: string) =>
      api.updateDashboard(binding.id, { filter_id: filterId }),
    onSuccess: onChanged,
  })

  const filters = useQuery({
    queryKey: ['filters', binding.superset_dashboard_id],
    queryFn: () => api.listNativeFilters(binding.superset_dashboard_id!),
    enabled: expanded && Boolean(binding.superset_dashboard_id),
  })

  const healthy = Boolean(binding.embed_uuid && binding.filter_id)

  return (
    <li className="ff-list__item">
      <div className="ff-list__row">
        <button
          type="button"
          className="ff-disclosure"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
        >
          {expanded ? '▾' : '▸'}
        </button>
        <span className={`ff-dot ${healthy ? 'ff-dot--ok' : 'ff-dot--warn'}`} />
        <span className="ff-list__title">{binding.name}</span>
        <span className="ff-list__meta">
          {binding.auto_created ? 'auto' : 'adopted'}
          {binding.superset_dashboard_id ? ` · #${binding.superset_dashboard_id}` : ''}
        </span>
      </div>

      {expanded && (
        <div className="ff-list__detail">
          <dl className="ff-summary">
            <dt>Embed UUID</dt>
            <dd>{binding.embed_uuid ?? '— missing'}</dd>
            <dt>Refresh filter</dt>
            <dd>{binding.filter_id ?? '— missing, no live refresh'}</dd>
          </dl>

          {binding.superset_dashboard_id && (
            <>
              <label className="ff-field__label" htmlFor={`filter-${binding.id}`}>
                Refresh filter
              </label>
              <select
                id={`filter-${binding.id}`}
                className="ff-input ff-input--compact"
                value={binding.filter_id ?? ''}
                onChange={(e) => setFilter.mutate(e.target.value)}
                disabled={filters.isPending}
              >
                <option value="">None — dashboard's own interval only</option>
                {filters.data?.map((f: SupersetNativeFilter) => (
                  <option key={f.id} value={f.id}>
                    {f.name}
                    {f.column ? ` · ${f.column}` : ''}
                    {f.is_time ? ' · time range' : ` · ${f.filter_type}`}
                  </option>
                ))}
              </select>
            </>
          )}

          <div className="ff-button-row">
            <button
              type="button"
              className="ff-button ff-button--ghost ff-button--small"
              onClick={() => repair.mutate()}
              disabled={repair.isPending}
              title="Create whatever is missing: dashboard, dataset, filter, embed"
            >
              {repair.isPending ? 'Repairing…' : 'Repair'}
            </button>
            <button
              type="button"
              className="ff-button ff-button--danger ff-button--small"
              onClick={() => {
                const msg = binding.auto_created
                  ? `Delete "${binding.name}" here AND in Superset?`
                  : `Remove "${binding.name}"? The Superset dashboard is kept.`
                if (confirm(msg)) remove.mutate()
              }}
              disabled={remove.isPending}
            >
              Remove
            </button>
          </div>

          {repair.isError && <p className="ff-error-banner">{repair.error.message}</p>}
          {remove.isError && <p className="ff-error-banner">{remove.error.message}</p>}
        </div>
      )}
    </li>
  )
}

function AdoptExisting({ onDone }: { onDone: () => void }) {
  const [selected, setSelected] = useState('')

  const available = useQuery({
    queryKey: ['superset-dashboards'],
    queryFn: api.listSupersetDashboards,
  })

  const adopt = useMutation({
    mutationFn: async () => {
      const dashboard = available.data?.find((d) => d.id === selected)
      if (!dashboard) throw new Error('Pick a dashboard first.')

      // Enable embedding if it is not already on, so the adopted binding is
      // immediately usable rather than half-configured.
      let uuid = (await api.getEmbeddedUuid(dashboard.id)).uuid
      uuid ??= (await api.enableEmbedding(dashboard.id, [window.location.origin])).uuid

      // Adopt an existing time-range filter if the dashboard has one.
      const filters = await api.listNativeFilters(dashboard.id)
      const timeFilter = filters.find((f) => f.is_time)

      return api.adoptDashboard({
        name: dashboard.title,
        superset_dashboard_id: dashboard.id,
        embed_uuid: uuid,
        filter_id: timeFilter?.id,
      })
    },
    onSuccess: onDone,
  })

  return (
    <div className="ff-inset">
      {available.isPending ? (
        <p className="ff-muted">Loading dashboards from Superset…</p>
      ) : available.data?.length === 0 ? (
        <p className="ff-muted">Superset has no dashboards yet.</p>
      ) : (
        <>
          <select
            className="ff-input ff-input--compact"
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
          >
            <option value="">Select a dashboard…</option>
            {available.data?.map((d) => (
              <option key={d.id} value={d.id}>
                {d.title}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="ff-button ff-button--small"
            onClick={() => adopt.mutate()}
            disabled={!selected || adopt.isPending}
          >
            {adopt.isPending ? 'Adopting…' : 'Adopt'}
          </button>
        </>
      )}
      {adopt.isError && <p className="ff-error-banner">{adopt.error.message}</p>}
    </div>
  )
}

// --- 3. forms --------------------------------------------------------------

function FormsSection() {
  const forms = useQuery({ queryKey: ['forms'], queryFn: api.listForms })
  const dashboards = useQuery({ queryKey: ['dashboards'], queryFn: api.listDashboards })

  return (
    <Section title="Forms">
      <p className="ff-muted ff-small">
        Supplied by an external form builder over <code>PUT /api/forms/{'{name}'}</code>.
        A form can feed any number of dashboards.
      </p>

      {forms.isPending && <p className="ff-muted">Loading…</p>}
      <ul className="ff-list">
        {forms.data?.map((form) => (
          <FormRow key={form.id} form={form} dashboards={dashboards.data ?? []} />
        ))}
      </ul>
    </Section>
  )
}

function FormRow({
  form,
  dashboards,
}: {
  form: FormSummary
  dashboards: DashboardBinding[]
}) {
  const queryClient = useQueryClient()
  const [expanded, setExpanded] = useState(false)

  const detail = useQuery({
    queryKey: ['form', form.id],
    queryFn: () => api.getForm(form.id),
    enabled: expanded,
  })

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['forms'] })
    queryClient.invalidateQueries({ queryKey: ['form', form.id] })
  }

  const toggleLink = useMutation({
    mutationFn: ({ dashboardId, linked }: { dashboardId: number; linked: boolean }) =>
      linked
        ? api.unlinkDashboard(form.id, dashboardId)
        : api.linkDashboard(form.id, dashboardId),
    onSuccess: invalidate,
  })

  return (
    <li className="ff-list__item">
      <div className="ff-list__row">
        <button
          type="button"
          className="ff-disclosure"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
        >
          {expanded ? '▾' : '▸'}
        </button>
        <span
          className={`ff-dot ${form.dashboard_ids.length ? 'ff-dot--ok' : 'ff-dot--warn'}`}
        />
        <span className="ff-list__title">{form.name}</span>
        <span className="ff-list__meta">
          {form.field_count} fields · {form.dashboard_ids.length} dashboards
        </span>
      </div>

      {expanded && (
        <div className="ff-list__detail">
          {detail.data && (
            <dl className="ff-summary">
              <dt>Stored in columns</dt>
              <dd>{detail.data.mapped_columns.join(', ') || '—'}</dd>
              <dt>Stored in payload</dt>
              <dd>{detail.data.payload_fields.join(', ') || '—'}</dd>
            </dl>
          )}

          <p className="ff-field__label">Feeds these dashboards</p>
          {dashboards.length === 0 ? (
            <p className="ff-muted ff-small">No dashboards exist yet.</p>
          ) : (
            <ul className="ff-checklist">
              {dashboards.map((binding) => {
                const linked = form.dashboard_ids.includes(binding.id)
                return (
                  <li key={binding.id}>
                    <label>
                      <input
                        type="checkbox"
                        checked={linked}
                        disabled={toggleLink.isPending}
                        onChange={() =>
                          toggleLink.mutate({ dashboardId: binding.id, linked })
                        }
                      />
                      {binding.name}
                    </label>
                  </li>
                )
              })}
            </ul>
          )}
          {toggleLink.isError && (
            <p className="ff-error-banner">{toggleLink.error.message}</p>
          )}
        </div>
      )}
    </li>
  )
}

// --- 4. this view ----------------------------------------------------------

function ThisViewSection() {
  const activeViewId = useActiveViewId()
  const queryClient = useQueryClient()

  const view = useQuery({
    queryKey: ['view', activeViewId],
    queryFn: () => api.getView(activeViewId!),
    enabled: activeViewId !== null,
  })
  const forms = useQuery({ queryKey: ['forms'], queryFn: api.listForms })
  const dashboards = useQuery({ queryKey: ['dashboards'], queryFn: api.listDashboards })

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ['view', activeViewId] })

  const addPanel = useMutation({
    mutationFn: (panel: {
      kind: 'form' | 'dashboard'
      form_definition_id?: number
      dashboard_binding_id?: number
    }) => api.addPanel(activeViewId!, panel),
    onSuccess: invalidate,
  })

  const removePanel = useMutation({
    mutationFn: (panelId: number) => api.removePanel(activeViewId!, panelId),
    onSuccess: invalidate,
  })

  if (activeViewId === null) return null

  const usedForms = new Set(
    view.data?.panels.filter((p) => p.kind === 'form').map((p) => p.form_definition_id),
  )
  const usedDashboards = new Set(
    view.data?.panels
      .filter((p) => p.kind === 'dashboard')
      .map((p) => p.dashboard_binding_id),
  )

  return (
    <Section title={`This view${view.data ? ` · ${view.data.name}` : ''}`}>
      <p className="ff-muted ff-small">
        Panels in this view. A view can hold any number of forms and dashboards.
      </p>

      <ul className="ff-list">
        {view.data?.panels.map((panel) => (
          <li key={panel.id} className="ff-list__item">
            <div className="ff-list__row">
              <span className="ff-badge">{panel.kind}</span>
              <span className="ff-list__title">{panel.title ?? panel.panel_key}</span>
              <button
                type="button"
                className="ff-button ff-button--danger ff-button--small"
                onClick={() => removePanel.mutate(panel.id)}
                disabled={removePanel.isPending}
              >
                Remove
              </button>
            </div>
          </li>
        ))}
      </ul>

      <p className="ff-field__label">Add a panel</p>
      <div className="ff-button-row ff-button-row--wrap">
        {forms.data
          ?.filter((f) => !usedForms.has(f.id))
          .map((f) => (
            <button
              key={`form-${f.id}`}
              type="button"
              className="ff-button ff-button--ghost ff-button--small"
              onClick={() => addPanel.mutate({ kind: 'form', form_definition_id: f.id })}
            >
              + form: {f.name}
            </button>
          ))}
        {dashboards.data
          ?.filter((d) => !usedDashboards.has(d.id))
          .map((d) => (
            <button
              key={`dash-${d.id}`}
              type="button"
              className="ff-button ff-button--ghost ff-button--small"
              onClick={() =>
                addPanel.mutate({ kind: 'dashboard', dashboard_binding_id: d.id })
              }
            >
              + dashboard: {d.name}
            </button>
          ))}
      </div>

      {addPanel.isError && <p className="ff-error-banner">{addPanel.error.message}</p>}

      <p className="ff-muted ff-small">
        Added panels appear after the layout is rebuilt — use Reset layout in a
        panel header.
      </p>
    </Section>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="ff-setup-section">
      <h2 className="ff-setup-section__title">{title}</h2>
      {children}
    </section>
  )
}
