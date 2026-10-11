/**
 * Fetch wrapper for the LocalFleet API.
 *
 * The backend refuses commands with HTTP 200 + {success: false, error} and
 * rejects invalid input with a non-2xx status (e.g. 422). Both count as
 * failures here, so callers only check `ok` and show `error`.
 */
export async function apiRequest(url, { method = 'POST', json, form } = {}) {
  const init = { method }
  if (json !== undefined) {
    init.headers = { 'Content-Type': 'application/json' }
    init.body = JSON.stringify(json)
  } else if (form) {
    init.body = form
  }

  let res
  try {
    res = await fetch(url, init)
  } catch (err) {
    return { ok: false, status: 0, data: {}, error: `Backend unreachable (${err.message})` }
  }
  const data = (await res.json().catch(() => null)) ?? {}
  const ok = res.ok && data.success !== false
  return { ok, status: res.status, data, error: ok ? null : describeError(res, data) }
}

function describeError(res, data) {
  if (data.error) return data.error
  // FastAPI request validation: {detail: [{loc, msg}, ...]} or {detail: "..."}
  if (Array.isArray(data.detail)) {
    return data.detail
      .map((d) => {
        const field = (d.loc || []).filter((p) => p !== 'body').join('.')
        return field ? `${field}: ${d.msg}` : d.msg
      })
      .join('; ')
  }
  if (typeof data.detail === 'string') return data.detail
  return res.ok ? 'Request refused' : `HTTP ${res.status}`
}

/** Validation warnings of an accepted command (older backends sent them in `error`). */
export function commandWarnings({ ok, data }) {
  if (!ok) return []
  if (Array.isArray(data.warnings) && data.warnings.length > 0) return data.warnings
  return data.error ? [data.error] : []
}
