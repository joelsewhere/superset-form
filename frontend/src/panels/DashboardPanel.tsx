import { useCallback, useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { embedDashboard } from '../vendor/superset-embedded-sdk'
import { api } from '../api/client'
import { config } from '../config'
import { subscribe } from '../events/bus'

/**
 * A dashboard panel, in one of two modes.
 *
 * VIEW mode — the read-only embed, authenticated with a guest token.
 *
 *   Refresh happens in place via `setDataMask`: the panel pushes a new upper
 *   bound of "now" into the dashboard's native time-range filter, which
 *   dispatches `updateDataMask` into its Redux store — the same path a user
 *   clicking a filter takes. Charts re-query inside the existing iframe, so
 *   there is nothing to flash. Because the filter value participates in the
 *   query cache key, each submit produces genuinely fresh data.
 *
 *   This needs unreleased builds of both sides; see
 *   src/vendor/superset-embedded-sdk/README.md.
 *
 * EDIT mode — Superset's own dashboard UI, in an iframe.
 *
 *   Editing is impossible through the embed: a guest token's user is anonymous
 *   and carries only GUEST_ROLE_NAME, so it can neither own a dashboard nor
 *   save one. Edit mode therefore drops the guest token entirely and frames
 *   Superset's normal URL with `?standalone=1`, relying on the operator's own
 *   Superset session.
 *
 *   That session cookie only reaches a cross-origin iframe when Superset sets
 *   SameSite=None (configured in superset/superset_config.py). Browsers that
 *   block it regardless — Safari in particular — will show Superset's login
 *   screen inside the frame instead, so the panel offers a new-tab fallback.
 */

/** Collapse a burst of rapid submissions into one re-query. */
const REFRESH_DEBOUNCE_MS = 400

/**
 * How far ahead of "now" the refresh filter's upper bound is set.
 *
 * The bound exists to change the query's cache key, not to exclude anything.
 * Pushing it into the future means a row written a moment ago can never fall
 * outside the window because of clock skew between this browser and the
 * database.
 */
const REFRESH_LOOKAHEAD_MS = 5 * 60_000

/**
 * Build the `time_range` value for the refresh filter.
 *
 * Superset splits this on " : " and treats an EMPTY side as unbounded, so
 * " : <timestamp>" means "everything up to <timestamp>". The literal string
 * "No filter" is only valid on its own — using it as the left-hand side
 * produces `Cannot parse time string [No filter]`.
 *
 * The format is Superset's own `%Y-%m-%dT%H:%M:%S`: no fractional seconds and
 * no trailing Z, both of which are riskier to parse. Because that is only
 * second-resolution, the value is forced to advance on every call so two
 * submissions in the same second still produce distinct cache keys — which is
 * the entire mechanism by which the refresh gets fresh data.
 */
let lastUntilMs = 0
function nextTimeRange(): string {
  const at = Math.max(Date.now() + REFRESH_LOOKAHEAD_MS, lastUntilMs + 1000)
  lastUntilMs = at
  // toISOString is UTC, matching how created_at is stored.
  return ` : ${new Date(at).toISOString().slice(0, 19)}`
}

/** DashboardStandaloneMode.HideNav — chrome-less, but fully interactive. */
const STANDALONE_HIDE_NAV = 1

type EmbeddedDashboard = Awaited<ReturnType<typeof embedDashboard>>
type Mode = 'view' | 'edit'

export function DashboardPanel({ bindingId }: { bindingId: number }) {
  const [mode, setMode] = useState<Mode>('view')

  const binding = useQuery({
    queryKey: ['dashboard', bindingId],
    queryFn: () => api.getDashboard(bindingId),
  })

  if (binding.isPending) {
    return <p className="ff-muted ff-panel__status">Loading dashboard…</p>
  }

  if (binding.error) {
    return (
      <div className="ff-error-banner ff-error-banner--block" role="alert">
        {binding.error.message}
      </div>
    )
  }

  const { embed_uuid, superset_dashboard_id, name } = binding.data

  return (
    <div className="ff-panel ff-panel--dashboard">
      <div className="ff-panel-toolbar">
        <span className="ff-panel-toolbar__name">{name}</span>
        <div className="ff-segmented" role="group" aria-label="Dashboard mode">
          <button
            type="button"
            className={mode === 'view' ? 'is-active' : ''}
            onClick={() => setMode('view')}
          >
            View
          </button>
          <button
            type="button"
            className={mode === 'edit' ? 'is-active' : ''}
            onClick={() => setMode('edit')}
            disabled={!superset_dashboard_id}
            title={
              superset_dashboard_id
                ? 'Edit in Superset, in place'
                : 'This binding has no Superset dashboard id yet'
            }
          >
            Edit
          </button>
        </div>
      </div>

      {mode === 'view' ? (
        <EmbeddedView bindingId={bindingId} embedUuid={embed_uuid} />
      ) : (
        <EditView dashboardId={superset_dashboard_id!} />
      )}
    </div>
  )
}

// --- view mode -------------------------------------------------------------

function EmbeddedView({
  bindingId,
  embedUuid,
}: {
  bindingId: number
  embedUuid: string | null
}) {
  const mountRef = useRef<HTMLDivElement | null>(null)
  const dashboardRef = useRef<EmbeddedDashboard | null>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const [message, setMessage] = useState<string | null>(null)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [refreshWarning, setRefreshWarning] = useState<string | null>(null)

  const binding = useQuery({
    queryKey: ['dashboard', bindingId],
    queryFn: () => api.getDashboard(bindingId),
  })
  const filterId = binding.data?.filter_id ?? null

  const filterIdRef = useRef<string | null>(null)
  filterIdRef.current = filterId

  useEffect(() => {
    if (!embedUuid) {
      setStatus('error')
      setMessage(
        'This dashboard has no embed UUID yet. Open Setup and run Repair on it.',
      )
      return
    }

    const element = mountRef.current
    if (!element) return

    setStatus('loading')
    setMessage(null)

    let cancelled = false

    embedDashboard({
      id: embedUuid,
      supersetDomain: config.supersetDomain,
      mountPoint: element,
      fetchGuestToken: () => api.getGuestToken(bindingId),
      dashboardUiConfig: {
        hideTitle: true,
        hideChartControls: false,
        filters: { expanded: false },
      },
    })
      .then((dashboard) => {
        // StrictMode double-mounts in development; without this guard the
        // second mount leaks the first iframe.
        if (cancelled) {
          dashboard.unmount()
          return
        }
        dashboardRef.current = dashboard
        setStatus('ready')
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setStatus('error')
        setMessage(err instanceof Error ? err.message : String(err))
      })

    return () => {
      cancelled = true
      dashboardRef.current?.unmount()
      dashboardRef.current = null
    }
    // Re-embedding on a UUID change is intentional: that is a different
    // dashboard, not a refresh of the current one.
  }, [embedUuid, bindingId])

  const pushRefresh = useCallback(async () => {
    const dashboard = dashboardRef.current
    if (!dashboard) return

    const currentFilterId = filterIdRef.current
    if (!currentFilterId) {
      setRefreshWarning(
        'No refresh filter is configured for this dashboard, so it cannot ' +
          'update immediately. Run Repair on it in Setup, or pick a filter there.',
      )
      return
    }

    setIsRefreshing(true)
    try {
      // Moving the upper bound changes the query cache key, which is what
      // forces a genuinely fresh read rather than a cached one.
      const timeRange = nextTimeRange()

      // Sent with `get`, so an embedded page predating setDataMask rejects
      // rather than silently dropping the call.
      await dashboard.setDataMask({
        [currentFilterId]: {
          extraFormData: { time_range: timeRange },
          filterState: { value: timeRange, label: 'Latest' },
        },
      })
      setRefreshWarning(null)
      await waitForChartsToSettle(dashboard)
    } catch (err) {
      setRefreshWarning(
        'Live refresh failed, so this dashboard will only update on its own ' +
          'interval. This usually means the Superset image predates setDataMask — ' +
          'check that its pin matches the vendored SDK. ' +
          (err instanceof Error ? err.message : String(err)),
      )
    } finally {
      setIsRefreshing(false)
    }
  }, [])

  useEffect(() => {
    const unsubscribe = subscribe('submission:created', ({ dashboardIds }) => {
      // Many-to-many: ignore submissions from forms that do not feed this one.
      if (!dashboardIds.includes(bindingId)) return

      if (debounceRef.current) clearTimeout(debounceRef.current)
      debounceRef.current = setTimeout(() => {
        void pushRefresh()
      }, REFRESH_DEBOUNCE_MS)
    })

    return () => {
      unsubscribe()
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [bindingId, pushRefresh])

  return (
    <div className="ff-panel__body">
      {status === 'error' && (
        <div className="ff-error-banner ff-error-banner--block" role="alert">
          <strong>Dashboard unavailable.</strong>
          <p>{message}</p>
        </div>
      )}

      {status === 'loading' && <p className="ff-muted ff-panel__status">Loading…</p>}

      {refreshWarning && (
        <div className="ff-error-banner ff-error-banner--block" role="alert">
          <strong>Live refresh unavailable.</strong>
          <p>{refreshWarning}</p>
        </div>
      )}

      {isRefreshing && (
        <div className="ff-refresh-pill" role="status" aria-live="polite">
          Updating…
        </div>
      )}

      {/* Never keyed or conditionally unmounted: remounting is precisely the
          flash this design exists to avoid. */}
      <div ref={mountRef} className="ff-embed" />
    </div>
  )
}

// --- edit mode -------------------------------------------------------------

function EditView({ dashboardId }: { dashboardId: string }) {
  const [loaded, setLoaded] = useState(false)
  const url =
    `${config.supersetDomain}/superset/dashboard/${encodeURIComponent(dashboardId)}/` +
    `?standalone=${STANDALONE_HIDE_NAV}`

  return (
    <div className="ff-panel__body">
      <div className="ff-edit-note">
        Editing as your Superset user.{' '}
        <a href={url} target="_blank" rel="noreferrer">
          Open in a new tab
        </a>{' '}
        if the frame shows a login screen — some browsers block the session
        cookie in a cross-site frame.
      </div>

      {!loaded && <p className="ff-muted ff-panel__status">Loading Superset…</p>}

      <iframe
        className="ff-embed"
        src={url}
        title="Edit dashboard in Superset"
        onLoad={() => setLoaded(true)}
      />
    </div>
  )
}

/**
 * Resolve once no chart reports itself as loading, or after a ceiling.
 * Drives the "Updating…" pill only, so a timeout is harmless.
 */
async function waitForChartsToSettle(
  dashboard: EmbeddedDashboard,
  timeoutMs = 10_000,
): Promise<void> {
  const startedAt = Date.now()
  const poll = 250

  // Let the re-query actually begin before checking whether it has finished.
  await new Promise((resolve) => setTimeout(resolve, poll))

  while (Date.now() - startedAt < timeoutMs) {
    try {
      const states = await dashboard.getChartStates()
      const anyLoading = Object.values(states ?? {}).some(
        (state) => (state as { chartStatus?: string })?.chartStatus === 'loading',
      )
      if (!anyLoading) return
    } catch {
      // Cosmetic only — degrade to the timeout rather than surfacing this.
      return
    }
    await new Promise((resolve) => setTimeout(resolve, poll))
  }
}
