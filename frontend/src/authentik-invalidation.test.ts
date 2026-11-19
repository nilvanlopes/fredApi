import { describe, expect, it, vi } from 'vitest';
// @ts-expect-error Vite allows this relative import of the public ESM asset.
import { redirectFromInvalidation } from '../public/authentik-invalidation.js';

describe('redirecionamento da invalidação do Authentik', () => {
  const origin = 'https://login-fred.nilvanlopes.com';

  it('avança diretamente para o Fred após o executor concluir o logout', async () => {
    const fetchImpl = vi.fn(async (url: URL, options: RequestInit) => ({
      ok: true,
      url: url.href,
      json: async () => ({ component: 'xak-flow-redirect', to: 'https://fred.nilvanlopes.com/' }),
      options,
    }));
    const replace = vi.fn();

    await redirectFromInvalidation({
      search: '?next=%2F&flow_token=abc&fred_standard_ui=1',
      origin,
      fetchImpl,
      replace,
    });

    const [requestUrl, options] = fetchImpl.mock.calls[0];
    expect(requestUrl.pathname).toBe('/api/v3/flows/executor/fred-invalidation-flow/');
    expect(requestUrl.searchParams.get('query')).toBe('next=%2F&flow_token=abc');
    expect(requestUrl.searchParams.has('fred_standard_ui')).toBe(false);
    expect(options).toMatchObject({ mode: 'same-origin', cache: 'no-store', credentials: 'same-origin', referrerPolicy: 'no-referrer' });
    expect(replace).toHaveBeenCalledWith('https://fred.nilvanlopes.com/');
  });

  it('retorna ao fluxo original com a marca de fallback quando a resposta não é esperada', async () => {
    const fetchImpl = vi.fn(async () => ({
      ok: true,
      url: `${origin}/api/v3/flows/executor/fred-invalidation-flow/`,
      json: async () => ({ component: 'ak-stage-identification' }),
    }));
    const replace = vi.fn();

    await redirectFromInvalidation({
      search: '?next=%2F&flow_token=abc',
      origin,
      fetchImpl,
      replace,
    });

    expect(replace).toHaveBeenCalledWith(
      `${origin}/if/flow/fred-invalidation-flow/?next=%2F&flow_token=abc&fred_standard_ui=1`,
    );
  });
});
