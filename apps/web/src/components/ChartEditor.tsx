"use client";

import { useEffect, useMemo, useState } from "react";
import { ChartCard } from "@/components/ChartCard";
import {
  api,
  type ChartPreview,
  type ChartSpec,
  type ChartType,
  type ColumnProfile,
  type RenderedChart,
  type SemanticType,
} from "@/lib/api";

type Aggregation = NonNullable<ChartSpec["aggregation"]>;
type Transform = "day" | "week" | "month" | "hour" | "weekday";

const CHART_TYPES: { value: ChartType; label: string }[] = [
  { value: "bar", label: "Barras" },
  { value: "line", label: "Líneas (evolución en el tiempo)" },
  { value: "pie", label: "Dona (partes de un total)" },
  { value: "kpi", label: "Indicador (una cifra)" },
  { value: "scatter", label: "Dispersión (dos métricas)" },
  { value: "table", label: "Tabla de datos" },
];

// Qué columnas sirven como eje X para cada tipo de gráfico.
const X_TYPES: Partial<Record<ChartType, SemanticType[]>> = {
  bar: ["categorical", "boolean", "datetime", "identifier", "numeric"],
  line: ["datetime"],
  pie: ["categorical", "boolean"],
  scatter: ["numeric"],
};

const AGGREGATIONS: Partial<Record<ChartType, Aggregation[]>> = {
  bar: ["count", "sum", "mean", "rate"],
  line: ["count", "sum", "mean", "rate"],
  pie: ["count", "sum"],
  kpi: ["count", "sum", "mean", "rate"],
};

const AGG_LABEL: Record<Aggregation, string> = {
  count: "Contar registros",
  sum: "Sumar",
  mean: "Promedio",
  rate: "Porcentaje de «sí»",
};

const TRANSFORMS: { value: Transform; label: string; line: boolean }[] = [
  { value: "day", label: "Por día", line: true },
  { value: "week", label: "Por semana", line: true },
  { value: "month", label: "Por mes", line: true },
  { value: "hour", label: "Por hora del día", line: false },
  { value: "weekday", label: "Por día de la semana", line: false },
];

const TRANSFORM_TITLE: Record<Transform, string> = {
  day: "día",
  week: "semana",
  month: "mes",
  hour: "hora del día",
  weekday: "día de la semana",
};

interface Draft {
  chart_type: ChartType;
  x: string | null;
  y: string | null;
  aggregation: Aggregation | null;
  x_transform: Transform | null;
  group_by: string | null;
  per_day: boolean;
  limit: number | null;
}

function of(columns: ColumnProfile[], types: SemanticType[]) {
  return columns.filter((c) => types.includes(c.semantic_type));
}

/** Ajusta el borrador para que solo tenga opciones compatibles con el tipo elegido. */
function normalize(d: Draft, columns: ColumnProfile[]): Draft {
  const next = { ...d };
  const type = (name: string | null) => columns.find((c) => c.name === name)?.semantic_type;

  const xOptions = of(columns, X_TYPES[next.chart_type] ?? []).map((c) => c.name);
  next.x = xOptions.length === 0 ? null : xOptions.includes(next.x ?? "") ? next.x : xOptions[0];

  const aggs = AGGREGATIONS[next.chart_type];
  next.aggregation = !aggs ? null : aggs.includes(next.aggregation!) ? next.aggregation : aggs[0];

  const yTypes: SemanticType[] =
    next.chart_type === "scatter" || next.aggregation === "sum" || next.aggregation === "mean"
      ? ["numeric"]
      : next.aggregation === "rate"
        ? ["boolean"]
        : [];
  const yOptions = of(columns, yTypes)
    .map((c) => c.name)
    .filter((n) => next.chart_type !== "scatter" || n !== next.x);
  if (next.aggregation === "count" && next.chart_type !== "scatter") {
    // Contar transacciones con importe (p. ej. "Pedidos") cuenta solo las de total > 0:
    // se conserva esa métrica oculta si ya venía en el gráfico.
    next.y = next.group_by && type(next.y) === "numeric" ? next.y : null;
  } else {
    next.y = yOptions.length === 0 ? null : yOptions.includes(next.y ?? "") ? next.y : yOptions[0];
  }

  if (type(next.x) === "datetime" && next.chart_type !== "kpi") {
    const allowed = TRANSFORMS.filter((t) => next.chart_type !== "line" || t.line).map((t) => t.value);
    if (!allowed.includes(next.x_transform!)) next.x_transform = "month";
  } else {
    next.x_transform = null;
  }
  if (next.chart_type === "kpi" || next.chart_type === "table") next.x = null;
  if (next.chart_type === "table") next.y = null;

  const groupable =
    ["kpi", "bar", "line"].includes(next.chart_type) && next.aggregation !== "rate";
  if (!groupable || next.group_by === next.x) next.group_by = null;
  if (!(next.x_transform === "hour" || next.x_transform === "weekday")) next.per_day = false;
  if (!(next.aggregation === "sum" || next.aggregation === "count")) next.per_day = false;
  if (next.chart_type !== "bar" || type(next.x) === "datetime") next.limit = null;
  return next;
}

function autoTitle(d: Draft): string {
  if (d.chart_type === "table") return "Datos";
  if (d.chart_type === "scatter") return `${d.y ?? "?"} vs ${d.x ?? "?"}`;
  const measure =
    d.aggregation === "sum"
      ? `Total de ${d.y}`
      : d.aggregation === "mean"
        ? `Promedio de ${d.y}`
        : d.aggregation === "rate"
          ? `% de ${d.y} = sí`
          : d.group_by
            ? `Número de ${d.group_by}`
            : "Número de registros";
  const daily = d.per_day ? " (promedio diario)" : "";
  if (d.chart_type === "kpi") return measure;
  const by = d.x_transform ? TRANSFORM_TITLE[d.x_transform] : d.x;
  return `${measure} por ${by}${daily}`;
}

function toSpec(d: Draft, title: string, reason: string): ChartSpec {
  return {
    ...d,
    title: title.trim() || autoTitle(d),
    score: 1,
    reason,
    source: "user",
  };
}

export function ChartEditor({
  datasetId,
  columns,
  initial,
  onSave,
  onClose,
}: {
  datasetId: string;
  columns: ColumnProfile[];
  initial?: ChartSpec;
  onSave: (chart: RenderedChart) => void;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState<Draft>(() =>
    normalize(
      {
        chart_type: initial?.chart_type ?? "bar",
        x: initial?.x ?? null,
        y: initial?.y ?? null,
        aggregation: initial?.aggregation ?? "count",
        x_transform: (initial?.x_transform as Transform | null) ?? null,
        group_by: initial?.group_by ?? null,
        per_day: initial?.per_day ?? false,
        limit: initial?.limit ?? null,
      },
      columns,
    ),
  );
  const [title, setTitle] = useState(initial?.title ?? "");
  const [titleTouched, setTitleTouched] = useState(Boolean(initial));
  const [preview, setPreview] = useState<ChartPreview | null>(null);
  const [loading, setLoading] = useState(true);

  const effectiveTitle = titleTouched ? title : autoTitle(draft);
  const reason = initial ? "Gráfico ajustado por ti." : "Gráfico creado por ti.";
  const spec = useMemo(() => toSpec(draft, effectiveTitle, reason), [draft, effectiveTitle, reason]);

  // Vista previa en vivo, con una pequeña espera para no pedir en cada tecla.
  useEffect(() => {
    let stale = false;
    const timer = setTimeout(() => {
      setLoading(true);
      api
        .previewChart(datasetId, spec)
        .then((p) => !stale && setPreview(p))
        .catch((e) =>
          !stale &&
          setPreview({ spec, data: null, error: null, errors: [(e as Error).message], warnings: [] }),
        )
        .finally(() => !stale && setLoading(false));
    }, 350);
    return () => {
      stale = true;
      clearTimeout(timer);
    };
  }, [datasetId, spec]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const update = (patch: Partial<Draft>) => setDraft((d) => normalize({ ...d, ...patch }, columns));
  const typeOf = (name: string | null) => columns.find((c) => c.name === name)?.semantic_type;

  const xOptions = of(columns, X_TYPES[draft.chart_type] ?? []);
  const aggs = AGGREGATIONS[draft.chart_type] ?? [];
  const yOptions =
    draft.chart_type === "scatter" || draft.aggregation === "sum" || draft.aggregation === "mean"
      ? of(columns, ["numeric"]).filter((c) => draft.chart_type !== "scatter" || c.name !== draft.x)
      : draft.aggregation === "rate"
        ? of(columns, ["boolean"])
        : [];
  const keyOptions = of(columns, ["identifier", "categorical"]).filter((c) => c.name !== draft.x);
  const showGroupBy = ["kpi", "bar", "line"].includes(draft.chart_type) && draft.aggregation !== "rate";
  const isDateX = typeOf(draft.x) === "datetime";
  const errors = preview?.errors ?? [];
  const warnings = preview?.warnings ?? [];
  const canSave = !loading && preview !== null && errors.length === 0;

  const field = "w-full rounded-lg border border-line bg-page px-3 py-2";

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="chart-editor-title"
        className="my-8 w-full max-w-5xl rounded-xl border border-line bg-surface p-5 shadow-xl"
      >
        <header className="mb-4 flex items-center justify-between gap-4">
          <h2 id="chart-editor-title" className="text-lg font-semibold">
            {initial ? "Editar gráfico" : "Crear gráfico"}
          </h2>
          <button onClick={onClose} className="text-sm text-ink-2" aria-label="Cerrar">
            ✕
          </button>
        </header>

        <div className="grid gap-6 lg:grid-cols-[minmax(0,20rem)_minmax(0,1fr)]">
          <form className="space-y-4 text-sm" onSubmit={(e) => e.preventDefault()}>
            <Labeled label="Tipo de gráfico">
              <select
                className={field}
                value={draft.chart_type}
                onChange={(e) => update({ chart_type: e.target.value as ChartType })}
              >
                {CHART_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
            </Labeled>

            {X_TYPES[draft.chart_type] && (
              <Labeled label={draft.chart_type === "scatter" ? "Eje X (métrica)" : "Agrupar por (eje X)"}>
                {xOptions.length === 0 ? (
                  <p className="text-danger">
                    No hay columnas compatibles con este tipo de gráfico.
                  </p>
                ) : (
                  <select
                    className={field}
                    value={draft.x ?? ""}
                    onChange={(e) => update({ x: e.target.value })}
                  >
                    {xOptions.map((c) => (
                      <option key={c.name} value={c.name}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                )}
              </Labeled>
            )}

            {isDateX && (
              <Labeled label="Agrupar la fecha">
                <select
                  className={field}
                  value={draft.x_transform ?? ""}
                  onChange={(e) => update({ x_transform: e.target.value as Transform })}
                >
                  {TRANSFORMS.filter((t) => draft.chart_type !== "line" || t.line).map((t) => (
                    <option key={t.value} value={t.value}>
                      {t.label}
                    </option>
                  ))}
                </select>
              </Labeled>
            )}

            {aggs.length > 0 && (
              <Labeled label="Cálculo">
                <select
                  className={field}
                  value={draft.aggregation ?? ""}
                  onChange={(e) => update({ aggregation: e.target.value as Aggregation })}
                >
                  {aggs.map((a) => (
                    <option key={a} value={a}>
                      {AGG_LABEL[a]}
                    </option>
                  ))}
                </select>
              </Labeled>
            )}

            {(draft.chart_type === "scatter" || (draft.aggregation && draft.aggregation !== "count")) && (
              <Labeled label={draft.chart_type === "scatter" ? "Eje Y (métrica)" : "Métrica"}>
                {yOptions.length === 0 ? (
                  <p className="text-danger">
                    {draft.aggregation === "rate"
                      ? "No hay columnas sí/no en este dataset."
                      : "No hay columnas numéricas disponibles."}
                  </p>
                ) : (
                  <select
                    className={field}
                    value={draft.y ?? ""}
                    onChange={(e) => update({ y: e.target.value })}
                  >
                    {yOptions.map((c) => (
                      <option key={c.name} value={c.name}>
                        {c.name}
                        {c.additive === false ? " (se suele promediar)" : ""}
                      </option>
                    ))}
                  </select>
                )}
              </Labeled>
            )}

            {showGroupBy && keyOptions.length > 0 && (
              <Labeled
                label="Calcular por transacción"
                hint="Si el archivo trae varias filas por pedido/ticket, elige su columna para contar pedidos y promediar su total, no filas."
              >
                <select
                  className={field}
                  value={draft.group_by ?? ""}
                  onChange={(e) => update({ group_by: e.target.value || null })}
                >
                  <option value="">Cada fila por separado</option>
                  {keyOptions.map((c) => (
                    <option key={c.name} value={c.name}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </Labeled>
            )}

            {(draft.x_transform === "hour" || draft.x_transform === "weekday") &&
              (draft.aggregation === "sum" || draft.aggregation === "count") && (
                <label className="flex items-start gap-2">
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={draft.per_day}
                    onChange={(e) => update({ per_day: e.target.checked })}
                  />
                  <span>
                    Promedio por día
                    <span className="block text-xs text-muted">
                      Recomendado: evita que un día de la semana gane solo por aparecer más veces.
                    </span>
                  </span>
                </label>
              )}

            {draft.chart_type === "bar" && !isDateX && (
              <Labeled label="Mostrar solo los primeros" hint="Vacío = todos.">
                <input
                  type="number"
                  min={1}
                  max={100}
                  className={field}
                  value={draft.limit ?? ""}
                  onChange={(e) => update({ limit: e.target.value ? Number(e.target.value) : null })}
                />
              </Labeled>
            )}

            <Labeled label="Título">
              <input
                className={field}
                value={effectiveTitle}
                onChange={(e) => {
                  setTitleTouched(true);
                  setTitle(e.target.value);
                }}
              />
            </Labeled>
          </form>

          <div className="min-w-0 space-y-3">
            <p className="text-xs font-medium text-ink-2">
              Vista previa {loading && <span className="text-muted">· actualizando…</span>}
            </p>
            {errors.length > 0 && (
              <ul className="space-y-1 rounded-lg border border-line p-3 text-sm" role="alert">
                {errors.map((e) => (
                  <li key={e} className="flex gap-2">
                    <span aria-hidden className="font-semibold text-danger">⚠</span>
                    <span>
                      <span className="sr-only">Error:</span> {e}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            {warnings.length > 0 && (
              <ul className="space-y-1 rounded-lg border border-line p-3 text-sm">
                {warnings.map((w) => (
                  <li key={w} className="flex gap-2">
                    <span aria-hidden className="font-semibold text-accent">ⓘ</span>
                    <span>
                      <span className="sr-only">Advertencia:</span> {w}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            {preview && errors.length === 0 && <ChartCard chart={preview} />}
          </div>
        </div>

        <footer className="mt-6 flex justify-end gap-2 text-sm">
          <button onClick={onClose} className="rounded-lg border border-line px-4 py-2">
            Cancelar
          </button>
          <button
            onClick={() => preview && onSave({ spec, data: preview.data, error: preview.error })}
            disabled={!canSave}
            className="rounded-lg bg-accent px-4 py-2 font-medium text-white disabled:opacity-50"
          >
            {initial ? "Guardar cambios" : "Agregar gráfico"}
          </button>
        </footer>
      </div>
    </div>
  );
}

function Labeled({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-ink-2">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-muted">{hint}</span>}
    </label>
  );
}
