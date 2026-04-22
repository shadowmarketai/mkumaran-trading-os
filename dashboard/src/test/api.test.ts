import { describe, it, expect, vi, beforeEach } from 'vitest';

// Dynamic import after localStorage is manipulated in each test so the
// axios baseURL + interceptor setup always runs clean.
async function loadApi() {
  vi.resetModules();
  return await import('../services/api');
}

describe('services/api', () => {
  beforeEach(() => {
    localStorage.clear();
    // Silence console.error during the tests — the module logs on 401
    vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  it('creates two axios instances with the expected baseURLs', async () => {
    const mod = await loadApi();
    const api = mod.default;
    const toolsApi = mod.toolsApi;

    expect(api.defaults.baseURL).toBe('/api');
    expect(toolsApi.defaults.baseURL).toBe('/');
  });

  it('exposes the main resource API modules used by pages', async () => {
    const mod = await loadApi();

    // Spot-check the modules referenced by App.tsx pages
    expect(mod.overviewApi).toBeDefined();
    expect(mod.signalApi).toBeDefined();
    expect(mod.tradeApi).toBeDefined();
    expect(mod.watchlistApi).toBeDefined();
    expect(mod.accuracyApi).toBeDefined();
    expect(mod.optionsApi).toBeDefined();
    expect(mod.signalMonitorApi).toBeDefined();
    expect(mod.marketMoversApi).toBeDefined();
    expect(mod.orderApi).toBeDefined();
    expect(mod.chartApi).toBeDefined();
  });

  it('has a sane per-request timeout configured', async () => {
    const mod = await loadApi();
    // baseline axios timeout for dashboard CRUD is 10s
    expect(mod.default.defaults.timeout).toBe(10000);
    // tools endpoints are heavier
    expect(mod.toolsApi.defaults.timeout).toBe(15000);
  });
});
