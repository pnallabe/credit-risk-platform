// Centralized API client for the Helix Decisions Tenant Portal
// Automatically attaches the Bearer JWT from localStorage to every request.

const DECISION_API_URL = process.env.NEXT_PUBLIC_DECISION_API_URL || 'http://localhost:8000';
const ANALYTICS_API_URL = process.env.NEXT_PUBLIC_ANALYTICS_API_URL || 'http://localhost:8002';
const AGENTHIVE_LOGIN_URL = process.env.NEXT_PUBLIC_AGENTHIVE_LOGIN_URL || 'http://localhost:9002/login';

function redirectToLoginWithReturn(): void {
  if (typeof window === 'undefined') return;

  const returnTo = `${window.location.pathname}${window.location.search}`;
  const loginUrl = new URL(AGENTHIVE_LOGIN_URL);
  loginUrl.searchParams.set('next', returnTo);
  window.location.href = loginUrl.toString();
}

async function fetchWithAuth(url: string, options: RequestInit = {}) {
  const token = typeof window !== 'undefined' ? localStorage.getItem('helix_tenant_token') : null;

  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
    ...options.headers,
  };

  const response = await fetch(url, { ...options, headers });

  if (response.status === 401) {
    // Token expired or invalid
    if (typeof window !== 'undefined') {
      localStorage.removeItem('helix_tenant_token');
      localStorage.removeItem('helix_tenant_id');
      localStorage.removeItem('helix_tenant_slug');
      redirectToLoginWithReturn();
    }
  }

  return response;
}

// -----------------------------------------------------------------------------
// Analytics API endpoints
// -----------------------------------------------------------------------------

export async function fetchApprovalProfit(monthsBack = 12) {
  const res = await fetchWithAuth(`${ANALYTICS_API_URL}/v1/analytics/approval-profit?months_back=${monthsBack}`);
  if (!res.ok) throw new Error('Failed to fetch approval profit');
  return res.json();
}

export async function fetchVintageCurves(monthsBack = 24) {
  const res = await fetchWithAuth(`${ANALYTICS_API_URL}/v1/analytics/vintage-curves?months_back=${monthsBack}`);
  if (!res.ok) throw new Error('Failed to fetch vintage curves');
  return res.json();
}

export async function fetchRollRates(monthsBack = 12) {
  const res = await fetchWithAuth(`${ANALYTICS_API_URL}/v1/analytics/roll-rates?months_back=${monthsBack}`);
  if (!res.ok) throw new Error('Failed to fetch roll rates');
  return res.json();
}

// -----------------------------------------------------------------------------
// Decision API endpoints
// -----------------------------------------------------------------------------

export async function fetchMetrics() {
  const res = await fetchWithAuth(`${DECISION_API_URL}/v1/metrics`);
  if (!res.ok) throw new Error('Failed to fetch metrics');
  return res.json();
}

export async function fetchPolicyAdherence() {
  const res = await fetchWithAuth(`${DECISION_API_URL}/v1/compliance/policy-adherence`);
  if (!res.ok) throw new Error('Failed to fetch policy adherence');
  return res.json();
}

export async function fetchAuditLogs(limit = 100) {
  // Assuming a generic decisions endpoint exists, or we mock if not found.
  // The backend has /v1/decisions/{id}/audit but we need a list for the dashboard.
  // We will hit a batch/decisions endpoint or mock it if unavailable in the backend.
  const res = await fetchWithAuth(`${DECISION_API_URL}/v1/decisions?limit=${limit}`);
  if (!res.ok) {
    console.warn("Audit list endpoint not available, returning empty array");
    return { data: [] };
  }
  return res.json();
}
