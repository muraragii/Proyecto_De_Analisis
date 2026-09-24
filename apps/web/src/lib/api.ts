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
  additive: boolean | null;
  stats: Record<string, unknown>;
}

export interface DataWarning {
  level: "info" | "warning";
  code: string;
  message: string;
  column: string | null;
}

export interface Dataset {
  id: string;
  name: string;
  filename: string;
  n_rows: number;
  n_cols: number;
  detected_industry: string | null;
  created_at: string;
  profile: {
    n_rows: number;
    n_cols: number;
    columns: ColumnProfile[];
    warnings: DataWarning[];
  } | null;
}

export interface ChartSpec {
  chart_type: ChartType;
  title: string;
  x: string | null;
  y: string | null;
  aggregation: "sum" | "mean" | "count" | null;
  x_transform: string | null;
  group_by: string | null;
  per_day: boolean;
  limit: number | null;
  score: number;
  reason: string;
  source: string;
}

/** partial: el periodo no está completo en los datos (primera/última semana o mes). */
export type Point = { x: string | number | null; y: number | null; partial?: boolean };

/** notes: aclaraciones para interpretar bien la cifra (top N, promedios diarios, huecos…). */
export type ChartData =
  | { value: number | null; notes?: string[] }
  | { points: Point[]; notes?: string[] }
  | { columns: string[]; rows: unknown[][]; total_rows: number };

export interface RenderedChart {
  spec: ChartSpec;
  data: ChartData | null;
  error: string | null;
}

/** Hallazgo en texto. basis: sobre qué datos y con qué prueba se calculó. */
export interface Insight {
  kind: string;
  title: string;
  text: string;
  tone: "positive" | "negative" | "neutral";
  basis: string;
  score: number;
}

export interface Recommendations {
  industry: string | null;
  detected_industry: string | null;
  detection_confidence: number;
  charts: RenderedChart[];
  insights: Insight[];
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
  insights: Insight[] | null;
}

export interface Organization {
  id: string;
  name: string;
  role: "owner" | "member";
}

export interface Me {
  user: { id: string; email: string; name: string };
  organization: Organization;
  organizations: Organization[];
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

/** Se emite cuando la API responde 401 fuera de /auth: la sesión expiró o se revocó. */
export const SESSION_EXPIRED_EVENT = "session-expired";

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  // credentials: la cookie de sesión (httpOnly) viaja con cada petición a la API.
  const res = await fetch(`${API_URL}${path}`, { ...init, headers, credentials: "include" });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const detail = Array.isArray(body?.detail)
      ? validationMessage(body.detail)
      : typeof body?.detail === "string"
        ? body.detail
        : res.statusText;
    if (res.status === 401 && !path.startsWith("/auth/")) {
      window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
    }
    throw new ApiError(detail || `Error ${res.status}`, res.status);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

const FIELD_LABEL: Record<string, string> = {
  email: "El correo",
  password: "La contraseña",
  name: "El nombre",
  organization_name: "El nombre del negocio",
};

/** Traduce los errores de validación de FastAPI (422) a un mensaje legible. */
function validationMessage(errors: { loc: string[]; type: string }[]): string {
  const first = errors[0];
  const field = FIELD_LABEL[first?.loc?.at(-1) ?? ""] ?? "Un campo";
  if (first?.type === "string_too_short") {
    return field === "La contraseña"
      ? "La contraseña debe tener al menos 8 caracteres"
      : `${field} es obligatorio`;
  }
  if (first?.type === "value_error" && field === "El correo") return "El correo no es válido";
  return `${field} no es válido`;
}

export const auth = {
  me: () => request<Me>("/auth/me"),
  login: (email: string, password: string) =>
    request<Me>("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  register: (body: {
    name: string;
    email: string;
    password: string;
    organization_name: string;
  }) => request<Me>("/auth/register", { method: "POST", body: JSON.stringify(body) }),
  logout: () => request<void>("/auth/logout", { method: "POST" }),
};

export const api = {
  industries: () => request<Industry[]>("/industries"),
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
    request<Dashboard>(`/public/dashboards/${token}`),
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
