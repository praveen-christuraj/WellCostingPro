/**
 * Product identity — the application name and the subtitle that sits beneath it.
 *
 * The wordmark, browser tab, print-sheet headers and sign-in footer all read from
 * here, so the two lines cannot drift apart between screens. The API has the same
 * pair in `backend/app/core/config.py` (`app_name` / `app_tagline`).
 */
export const APP_NAME = 'WellCostIQ'
export const APP_TAGLINE = 'Well Cost Estimation & Tracking'

/**
 * Browser-tab title: `Page · WellCostIQ`, or the application name with its
 * subtitle when no page is selected (the sign-in screen).
 */
export const pageTitle = (page?: string | null): string =>
  page ? `${page} · ${APP_NAME}` : `${APP_NAME} — ${APP_TAGLINE}`
