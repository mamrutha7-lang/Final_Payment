/**
 * One JSON call to the API, and the server's sentence when it refuses.
 *
 * Shared by screens that only need "fetch this, or tell me why not": the fee
 * screens (as `feeApi`, core/fees.ts) and the leave screens (core/leave.ts).
 * A screen with its own needs (streaming, uploads, a file download) calls
 * `fetch` itself; this does not try to cover those.
 */

import { environment } from '../../environments/environment';

/** The server's sentence for a refusal, or a fallback that names the status.
 *  A 422 from FastAPI carries a LIST of problems, which is joined. */
export async function detailOf(res: Response, fallback: string): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body?.detail === 'string') return body.detail;
    if (Array.isArray(body?.detail)) {
      return body.detail
        .map((d: { msg?: string }) => (d?.msg ?? '').replace(/^Value error, /, ''))
        .filter(Boolean)
        .join(' ');
    }
  } catch {
    /* not JSON */
  }
  return `${fallback} (${res.status})`;
}

/** A JSON call to the API. Throws an Error whose message is the screen's sentence. */
export async function apiJson<T>(path: string, init: RequestInit = {}, fallback = 'Something went wrong'): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${environment.apiBase}${path}`, {
      credentials: 'include',
      ...init,
      headers: init.body ? { 'Content-Type': 'application/json', ...(init.headers ?? {}) } : init.headers,
    });
  } catch {
    throw new Error('Could not reach the server. Check your connection and try again.');
  }
  if (!res.ok) throw new Error(await detailOf(res, fallback));
  return (await res.json()) as T;
}
