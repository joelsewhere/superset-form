/**
 * Build-time configuration.
 *
 * Only the API location and Superset's browser-facing domain live here. The
 * dashboard binding (embed UUID and native filter id) is *runtime* config
 * fetched from `GET /api/config`, so it can be changed from the Setup panel
 * without a rebuild — see src/api/client.ts.
 */

export const config = {
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000',
  supersetDomain: import.meta.env.VITE_SUPERSET_DOMAIN ?? 'http://localhost:8088',
} as const
