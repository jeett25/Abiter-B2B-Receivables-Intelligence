// Thin typed client over backend/app/api -- every route there is GET-only
// and reads already-persisted data (see docs/api-DECISIONS.md), so there is
// deliberately no caching layer or mutation support here.

import { AttributionResponse, DecisionTrace, DemoFixture, InvoiceSummary, InvoiceTimeline, MetricsResponse } from "./types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function fetchJson<T>(path: string, params?: Record<string, string | number | undefined>): Promise<T> {
  const url = new URL(path, API_BASE_URL);
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined) {
        url.searchParams.set(key, String(value));
      }
    }
  }

  let res: Response;
  try {
    // Live dashboard data -- never let Next's fetch cache serve a stale
    // decision/metrics snapshot.
    res = await fetch(url, { cache: "no-store" });
  } catch {
    throw new ApiError(0, `Could not reach the API at ${API_BASE_URL}. Is the backend running?`);
  }

  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new ApiError(res.status, `${res.status} ${res.statusText}${detail ? `: ${detail}` : ""}`);
  }

  return res.json() as Promise<T>;
}

export interface ListInvoicesParams {
  currentState?: string;
  segment?: string;
  invoiceNumber?: string;
  limit?: number;
  offset?: number;
}

// GET /api/invoices
export function listInvoices(params: ListInvoicesParams = {}): Promise<InvoiceSummary[]> {
  return fetchJson<InvoiceSummary[]>("/api/invoices", {
    current_state: params.currentState,
    segment: params.segment,
    invoice_number: params.invoiceNumber,
    limit: params.limit,
    offset: params.offset,
  });
}

// GET /api/invoices/{id}
export function getInvoice(invoiceId: string): Promise<InvoiceSummary> {
  return fetchJson<InvoiceSummary>(`/api/invoices/${invoiceId}`);
}

// GET /api/invoices/{id}/decision
export function getDecision(invoiceId: string): Promise<DecisionTrace> {
  return fetchJson<DecisionTrace>(`/api/invoices/${invoiceId}/decision`);
}

// GET /api/invoices/{id}/timeline
export function getTimeline(invoiceId: string): Promise<InvoiceTimeline> {
  return fetchJson<InvoiceTimeline>(`/api/invoices/${invoiceId}/timeline`);
}

// GET /api/metrics
export function getMetrics(): Promise<MetricsResponse> {
  return fetchJson<MetricsResponse>("/api/metrics");
}

// GET /api/attribution. include_diagnostics deliberately left at its
// default (false) -- those fields are gated hidden-ground-truth diagnostics
// (see docs/api-DECISIONS.md), not for a production-facing screen.
// include_cuped=true is safe for production (not hidden-ground-truth-
// informed) -- see app/attribution/cuped.py.
export function getAttribution(): Promise<AttributionResponse> {
  return fetchJson<AttributionResponse>("/api/attribution?include_cuped=true");
}

// GET /api/demo-fixtures
export function getDemoFixtures(): Promise<DemoFixture[]> {
  return fetchJson<DemoFixture[]>("/api/demo-fixtures");
}
