export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type SemanticType =
  | "numeric"
  | "categorical"
  | "datetime"
  | "boolean"
  | "identifier"
  | "text";

export type ChartType = "bar" | "line" | "pie" | "scatter" | "kpi" | "table";

export interface ColumnProfile {
  name: string;
  semantic_type: SemanticType;
  source_dtype: string;
  null_ratio: number;
  n_unique: number;
  unique_ratio: number;
  geo_role: "lat" | "lon" | "region" | null;
  stats: Record<string, unknown>;
}

export interface Dataset {
  id: string;
  name: string;
  filename: string;
  n_rows: number;
  n_cols: number;
  detected_industry: string | null;
  created_at: string;
  profile: { n_rows: number; n_cols: number; columns: ColumnProfile[] } | null;
}

export interface ChartSpec {
  chart_type: ChartType;
  title: string;
  x: string | null;
  y: string | null;
  aggregation: "sum" | "mean" | "count" | null;
  x_transform: string | null;
  limit: number | null;
  score: number;
  reason: string;
  source: string;
}

export type Point = { x: string | number | null; y: number | null };

export type ChartData =
  | { value: number | null }
  | { points: Point[] }
  | { columns: string[]; rows: unknown[][]; total_rows: number };

export interface RenderedChart {
  spec: ChartSpec;
  data: ChartData | null;
  error: string | null;
}

export interface Recommendations {
  industry: string | null;
  detected_industry: string | null;
  detection_confidence: number;
  charts: RenderedChart[];
}

export interface Industry {
  id: string;
  name: string;
  description: string;
}

export interface Dashboard {
  id: string;
  dataset_id: string;
  title: string;
  industry: string | null;
  share_token: string | null;
  created_at: string;
  updated_at: string;
  charts: RenderedChart[] | null;
}

const TENANT_KEY = "tenant_id";

/** PROVISIONAL hasta tener autenticación: un tenant por navegador. */
export function tenantId(): string {
  try {
    let id = localStorage.getItem(TENANT_KEY);
    if (!id) {
      id = crypto.randomUUID();
      localStorage.setItem(TENANT_KEY, id);
    }
    return id;
  } catch {
    return "demo";
  }
}

async function request<T>(path: string, init: RequestInit = {}, auth = true): Promise<T> {
  const headers = new Headers(init.headers);
  if (auth) headers.set("X-Tenant-ID", tenantId());
  if (init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(`${API_URL}${path}`, { ...init, headers });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const detail = typeof body?.detail === "string" ? body.detail : res.statusText;
    throw new Error(detail || `Error ${res.status}`);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

export const api = {
  industries: () => request<Industry[]>("/industries", {}, false),
  datasets: () => request<Dataset[]>("/datasets"),
  dataset: (id: string) => request<Dataset>(`/datasets/${id}`),
  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Dataset>("/datasets", { method: "POST", body: form });
  },
  recommendations: (id: string, industry: string) =>
    request<Recommendations>(
      `/datasets/${id}/recommendations?industry=${encodeURIComponent(industry)}`,
    ),
  dashboards: () => request<Dashboard[]>("/dashboards"),
  dashboard: (id: string) => request<Dashboard>(`/dashboards/${id}`),
  createDashboard: (body: {
    dataset_id: string;
    title: string;
    industry: string | null;
    charts: ChartSpec[];
  }) => request<Dashboard>("/dashboards", { method: "POST", body: JSON.stringify(body) }),
  deleteDashboard: (id: string) => request<void>(`/dashboards/${id}`, { method: "DELETE" }),
  share: (id: string) => request<Dashboard>(`/dashboards/${id}/share`, { method: "POST" }),
  unshare: (id: string) => request<Dashboard>(`/dashboards/${id}/share`, { method: "DELETE" }),
  publicDashboard: (token: string) =>
    request<Dashboard>(`/public/dashboards/${token}`, {}, false),
};

const numberFormat = new Intl.NumberFormat("es-MX", { maximumFractionDigits: 2 });
const compactFormat = new Intl.NumberFormat("es-MX", {
  notation: "compact",
  maximumFractionDigits: 1,
});

export function formatNumber(value: unknown, compact = false): string {
  if (typeof value !== "number") return value == null ? "—" : String(value);
  return (compact && Math.abs(value) >= 10_000 ? compactFormat : numberFormat).format(value);
}
