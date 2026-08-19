import type { DockviewApi } from 'dockview'
import type { Panel } from '../api/client'

export const SETUP_PANEL_KEY = '__setup__'

/**
 * Lay panels out from scratch, used when a view has no saved layout yet.
 *
 * Forms go on the left as a tabbed group, dashboards to their right. Once the
 * user rearranges anything, the serialised layout takes over and this is not
 * consulted again for that view.
 */
export function buildInitialLayout(api: DockviewApi, panels: Panel[]): void {
  api.clear()

  const forms = panels.filter((p) => p.kind === 'form')
  const dashboards = panels.filter((p) => p.kind === 'dashboard')

  let firstFormKey: string | null = null
  forms.forEach((panel) => {
    api.addPanel({
      id: panel.panel_key,
      component: 'form',
      title: panel.title ?? 'Form',
      params: { panelId: panel.id, formId: panel.form_definition_id },
      ...(firstFormKey
        ? { position: { referencePanel: firstFormKey, direction: 'within' } }
        : {}),
    })
    firstFormKey ??= panel.panel_key
  })

  let firstDashboardKey: string | null = null
  dashboards.forEach((panel) => {
    api.addPanel({
      id: panel.panel_key,
      component: 'dashboard',
      title: panel.title ?? 'Dashboard',
      params: { panelId: panel.id, bindingId: panel.dashboard_binding_id },
      position: firstDashboardKey
        ? { referencePanel: firstDashboardKey, direction: 'within' }
        : firstFormKey
          ? { referencePanel: firstFormKey, direction: 'right' }
          : undefined,
    })
    firstDashboardKey ??= panel.panel_key
  })

  addSetupPanel(api, firstFormKey)

  // Give the dashboards the larger share to start with.
  if (firstFormKey && firstDashboardKey) {
    api.getPanel(firstFormKey)?.api.setSize({ width: Math.round(api.width * 0.38) })
    api.getPanel(firstFormKey)?.api.setActive()
  }
}

/** Setup always exists, and is never part of the persisted panel list. */
export function addSetupPanel(api: DockviewApi, referenceKey: string | null): void {
  if (api.getPanel(SETUP_PANEL_KEY)) return

  api.addPanel({
    id: SETUP_PANEL_KEY,
    component: 'setup',
    title: 'Setup',
    params: {},
    ...(referenceKey
      ? { position: { referencePanel: referenceKey, direction: 'within' } }
      : {}),
  })
}
