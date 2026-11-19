const FLOW_PATH = '/if/flow/fred-invalidation-flow/';
const EXECUTOR_PATH = '/api/v3/flows/executor/fred-invalidation-flow/';
const FALLBACK_PARAMETER = 'fred_standard_ui';
const FRED_PORTAL_URL = 'https://fred.nilvanlopes.com/';

/**
 * @param {{ search: string; origin: string; fetchImpl: (input: URL, init: RequestInit) => Promise<Pick<Response, 'ok' | 'url' | 'json'>>; replace: (url: string) => void }} options
 */
export async function redirectFromInvalidation({ search, origin, fetchImpl, replace }) {
  const originalQuery = new URLSearchParams(search);
  originalQuery.delete(FALLBACK_PARAMETER);

  const executorUrl = new URL(EXECUTOR_PATH, origin);
  executorUrl.searchParams.set('query', originalQuery.toString());

  try {
    const response = await fetchImpl(executorUrl, {
      mode: 'same-origin',
      cache: 'no-store',
      credentials: 'same-origin',
      referrerPolicy: 'no-referrer',
    });
    const responseUrl = new URL(response.url);
    if (!response.ok || responseUrl.origin !== origin || responseUrl.pathname !== EXECUTOR_PATH) {
      throw new Error('Unexpected invalidation response');
    }

    const result = await response.json();
    if (result?.component !== 'xak-flow-redirect' || result.to !== FRED_PORTAL_URL) {
      throw new Error('Unexpected invalidation stage');
    }

    replace(result.to);
  } catch {
    const fallbackUrl = new URL(FLOW_PATH, origin);
    originalQuery.set(FALLBACK_PARAMETER, '1');
    fallbackUrl.search = originalQuery.toString();
    replace(fallbackUrl.href);
  }
}

if (typeof window !== 'undefined' && window.location.pathname === FLOW_PATH) {
  void redirectFromInvalidation({
    search: window.location.search,
    origin: window.location.origin,
    fetchImpl: window.fetch.bind(window),
    replace: (url) => window.location.replace(url),
  });
}
