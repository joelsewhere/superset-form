import { config } from '../config'

// --- forms -----------------------------------------------------------------

export type FieldType = 'text' | 'textarea' | 'number' | 'select' | 'date'

export interface FormFieldSpec {
  name: string
  label: string
  type: FieldType
  required: boolean
  help_text: string | null
  options: string[] | null
  min: number | null
  max: number | null
  step: number | null
  placeholder: string | null
}

export interface FormSummary {
  id: number
  name: string
  field_count: number
  dashboard_ids: number[]
}

export interface FormRead {
  id: number
  name: string
  fields: FormFieldSpec[]
  dashboard_ids: number[]
  updated_at: string | null
  mapped_columns: string[]
  payload_fields: string[]
}

export interface Submission {
  id: string
  form_definition_id: number | null
  region: string
  product: string
  units: number
  unit_price: number
  sale_date: string
  notes: string | null
  payload: Record<string, unknown>
  created_at: string
}

// --- dashboards ------------------------------------------------------------

export interface DashboardBinding {
  id: number
  name: string
  superset_dashboard_id: string | null
  embed_uuid: string | null
  filter_id: string | null
  auto_created: boolean
  updated_at: string | null
}

// --- views -----------------------------------------------------------------

export type PanelKind = 'form' | 'dashboard'

export interface Panel {
  id: number
  panel_key: string
  kind: PanelKind
  title: string | null
  position: number
  form_definition_id: number | null
  dashboard_binding_id: number | null
}

export interface ViewSummary {
  id: number
  name: string
  is_default: boolean
  panel_count: number
}

export interface View {
  id: number
  name: string
  is_default: boolean
  layout: Record<string, unknown> | null
  panels: Panel[]
}

// --- Superset discovery ----------------------------------------------------

export interface SupersetStatus {
  reachable: boolean
  authenticated: boolean
  username: string | null
  url: string
  detail: string | null
}

export interface SupersetDashboard {
  id: string
  title: string
  status: string | null
}

export interface SupersetNativeFilter {
  id: string
  name: string
  filter_type: string
  column: string | null
  is_time: boolean
}

// --- transport -------------------------------------------------------------

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${config.apiBaseUrl}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })

  if (!response.ok) {
    // Surface the API's own message where there is one — several endpoints
    // return actionable setup instructions rather than a bare status.
    let detail = `${response.status} ${response.statusText}`
    try {
      const body = await response.json()
      if (body?.detail) {
        detail =
          typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
      }
    } catch {
      /* response had no JSON body */
    }
    throw new Error(detail)
  }

  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

const json = (method: string, body?: unknown): RequestInit => ({
  method,
  ...(body === undefined ? {} : { body: JSON.stringify(body) }),
})

export const api = {
  // views
  listViews: () => request<ViewSummary[]>('/api/views'),
  getDefaultView: () => request<View>('/api/views/default'),
  getView: (id: number) => request<View>(`/api/views/${id}`),
  createView: (name: string, isDefault = false) =>
    request<View>('/api/views', json('POST', { name, is_default: isDefault })),
  saveLayout: (viewId: number, layout: Record<string, unknown> | null) =>
    request<View>(`/api/views/${viewId}/layout`, json('PUT', { layout })),
  addPanel: (
    viewId: number,
    panel: {
      kind: PanelKind
      form_definition_id?: number
      dashboard_binding_id?: number
      title?: string
    },
  ) => request<View>(`/api/views/${viewId}/panels`, json('POST', panel)),
  removePanel: (viewId: number, panelId: number) =>
    request<View>(`/api/views/${viewId}/panels/${panelId}`, json('DELETE')),

  // forms
  listForms: () => request<FormSummary[]>('/api/forms'),
  getForm: (id: number) => request<FormRead>(`/api/forms/${id}`),
  getFormSchema: (id: number) => request<FormFieldSpec[]>(`/api/forms/${id}/schema`),
  linkDashboard: (formId: number, dashboardId: number) =>
    request<FormRead>(`/api/forms/${formId}/dashboards/${dashboardId}`, json('POST')),
  unlinkDashboard: (formId: number, dashboardId: number) =>
    request<FormRead>(`/api/forms/${formId}/dashboards/${dashboardId}`, json('DELETE')),

  // submissions
  createSubmission: (formId: number, payload: Record<string, unknown>) =>
    request<Submission>(`/api/forms/${formId}/submissions`, json('POST', payload)),
  listFormSubmissions: (formId: number, limit = 5) =>
    request<Submission[]>(`/api/forms/${formId}/submissions?limit=${limit}`),

  // dashboard bindings
  listDashboards: () => request<DashboardBinding[]>('/api/dashboards'),
  getDashboard: (id: number) => request<DashboardBinding>(`/api/dashboards/${id}`),
  createBlankDashboard: (name: string) =>
    request<DashboardBinding>(
      `/api/dashboards/blank?name=${encodeURIComponent(name)}`,
      json('POST'),
    ),
  adoptDashboard: (payload: {
    name: string
    superset_dashboard_id?: string
    embed_uuid?: string
    filter_id?: string
  }) => request<DashboardBinding>('/api/dashboards', json('POST', payload)),
  updateDashboard: (
    id: number,
    patch: Partial<Pick<DashboardBinding, 'name' | 'superset_dashboard_id' | 'embed_uuid' | 'filter_id'>>,
  ) => request<DashboardBinding>(`/api/dashboards/${id}`, json('PATCH', patch)),
  repairDashboard: (id: number) =>
    request<DashboardBinding>(`/api/dashboards/${id}/provision`, json('POST')),
  deleteDashboard: (id: number, deleteInSuperset = false) =>
    request<void>(
      `/api/dashboards/${id}?delete_in_superset=${deleteInSuperset}`,
      json('DELETE'),
    ),

  // superset
  getGuestToken: async (bindingId: number) => {
    const { token } = await request<{ token: string }>(
      `/api/superset/guest-token/${bindingId}`,
      json('POST'),
    )
    return token
  },
  getSupersetStatus: () => request<SupersetStatus>('/api/superset/status'),
  listSupersetDashboards: () =>
    request<SupersetDashboard[]>('/api/superset/dashboards'),
  getEmbeddedUuid: (dashboardId: string) =>
    request<{ uuid: string | null }>(
      `/api/superset/dashboards/${encodeURIComponent(dashboardId)}/embedded`,
    ),
  enableEmbedding: (dashboardId: string, allowedDomains: string[] = []) =>
    request<{ uuid: string }>(
      `/api/superset/dashboards/${encodeURIComponent(dashboardId)}/embedded`,
      json('POST', { allowed_domains: allowedDomains }),
    ),
  listNativeFilters: (dashboardId: string) =>
    request<SupersetNativeFilter[]>(
      `/api/superset/dashboards/${encodeURIComponent(dashboardId)}/filters`,
    ),
}
