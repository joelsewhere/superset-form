import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { DockviewReact } from 'dockview'
import type { DockviewApi, DockviewReadyEvent, IDockviewPanelProps } from 'dockview'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from './api/client'
import { CollapseProvider } from './layout/CollapseContext'
import { HeaderActions } from './layout/HeaderActions'
import { PanelTab } from './layout/PanelTab'
import { ViewProvider } from './layout/ViewContext'
import { ViewSwitcher } from './layout/ViewSwitcher'
import { useCollapse } from './layout/useCollapse'
import { SETUP_PANEL_KEY, addSetupPanel, buildInitialLayout } from './layout/buildLayout'
import { DashboardPanel } from './panels/DashboardPanel'
import { FormPanel } from './panels/FormPanel'
import { SetupPanel } from './panels/SetupPanel'

const LAYOUT_SAVE_DEBOUNCE_MS = 600
const ACTIVE_VIEW_KEY = 'frontflow.activeViewId'

/** Panels receive their target's id through dockview's params. */
const components = {
  form: (props: IDockviewPanelProps<{ formId: number }>) => (
    <FormPanel formId={props.params.formId} />
  ),
  dashboard: (props: IDockviewPanelProps<{ bindingId: number }>) => (
    <DashboardPanel bindingId={props.params.bindingId} />
  ),
  setup: () => <SetupPanel />,
}

const tabComponents = { default: PanelTab }

export function App() {
  const queryClient = useQueryClient()
  const containerRef = useRef<HTMLDivElement | null>(null)
  const apiRef = useRef<DockviewApi | null>(null)
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Suppresses layout persistence while we are the ones mutating the dock,
  // so restoring a view does not immediately save a half-built layout back.
  const applying = useRef(false)

  const [activeViewId, setActiveViewId] = useState<number | null>(() => {
    const stored = localStorage.getItem(ACTIVE_VIEW_KEY)
    return stored ? Number(stored) : null
  })

  const defaultView = useQuery({
    queryKey: ['view', 'default'],
    queryFn: api.getDefaultView,
    enabled: activeViewId === null,
  })

  useEffect(() => {
    if (activeViewId === null && defaultView.data) {
      setActiveViewId(defaultView.data.id)
    }
  }, [activeViewId, defaultView.data])

  const view = useQuery({
    queryKey: ['view', activeViewId],
    queryFn: () => api.getView(activeViewId!),
    enabled: activeViewId !== null,
  })

  const { toggle, isCollapsed } = useCollapse(containerRef)

  const persist = useCallback(() => {
    const dockApi = apiRef.current
    if (!dockApi || activeViewId === null || applying.current) return

    if (saveTimer.current) clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(() => {
      api
        .saveLayout(activeViewId, dockApi.toJSON() as unknown as Record<string, unknown>)
        .catch((err) => console.warn('[FrontFlow] Could not persist layout.', err))
    }, LAYOUT_SAVE_DEBOUNCE_MS)
  }, [activeViewId])

  /** Render a view into the dock: saved layout if there is one, else built. */
  const applyView = useCallback(() => {
    const dockApi = apiRef.current
    if (!dockApi || !view.data) return

    applying.current = true
    try {
      if (view.data.layout) {
        try {
          dockApi.fromJSON(view.data.layout as never)
          // Setup is not a persisted panel, so a restored layout will not
          // contain it.
          addSetupPanel(dockApi, view.data.panels[0]?.panel_key ?? null)
        } catch (err) {
          // A layout saved against panels that have since been removed will
          // throw. Rebuilding beats leaving a blank screen.
          console.warn('[FrontFlow] Saved layout unusable; rebuilding.', err)
          buildInitialLayout(dockApi, view.data.panels)
        }
      } else {
        buildInitialLayout(dockApi, view.data.panels)
      }
    } finally {
      // Let dockview settle before re-enabling persistence, or the restore
      // itself is written straight back.
      setTimeout(() => {
        applying.current = false
      }, 0)
    }
  }, [view.data])

  useEffect(() => {
    if (activeViewId !== null) localStorage.setItem(ACTIVE_VIEW_KEY, String(activeViewId))
  }, [activeViewId])

  useEffect(() => {
    applyView()
  }, [applyView])

  const onReady = useCallback(
    (event: DockviewReadyEvent) => {
      apiRef.current = event.api
      event.api.onDidLayoutChange(() => persist())
      applyView()
    },
    [applyView, persist],
  )

  const resetLayout = useCallback(() => {
    const dockApi = apiRef.current
    if (!dockApi || !view.data || activeViewId === null) return

    applying.current = true
    buildInitialLayout(dockApi, view.data.panels)
    setTimeout(() => {
      applying.current = false
    }, 0)

    api.saveLayout(activeViewId, null).then(() => {
      queryClient.invalidateQueries({ queryKey: ['view', activeViewId] })
    })
  }, [activeViewId, queryClient, view.data])

  const collapseValue = useMemo(
    () => ({ toggle, isCollapsed, resetLayout }),
    [toggle, isCollapsed, resetLayout],
  )

  const viewValue = useMemo(() => ({ activeViewId }), [activeViewId])

  return (
    <ViewProvider value={viewValue}>
    <CollapseProvider value={collapseValue}>
      <div className="ff-app">
        <header className="ff-appbar">
          <h1 className="ff-appbar__title">FrontFlow BI</h1>
          <ViewSwitcher activeViewId={activeViewId} onSelect={setActiveViewId} />
          <p className="ff-appbar__hint">
            Drag a tab to any edge to re-dock · double-click a tab to collapse
          </p>
        </header>

        {view.error && (
          <div className="ff-error-banner ff-error-banner--block" role="alert">
            {view.error.message}
          </div>
        )}

        <div className="ff-dock" ref={containerRef}>
          <DockviewReact
            components={components}
            tabComponents={tabComponents}
            rightHeaderActionsComponent={HeaderActions}
            onReady={onReady}
            className="dockview-theme-abyss"
          />
        </div>
      </div>
    </CollapseProvider>
    </ViewProvider>
  )
}

export { SETUP_PANEL_KEY }
