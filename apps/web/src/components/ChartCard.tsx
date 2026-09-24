"use client";

import { useEffect, useState, type ReactNode } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { formatNumber, type ChartData, type Point, type RenderedChart } from "@/lib/api";

const TOKENS = [
  "surface", "text-primary", "text-secondary", "text-muted", "grid", "axis",
  "series-1", "series-2", "series-3", "series-4", "series-5", "series-6",
] as const;
type Theme = Record<(typeof TOKENS)[number], string>;

/** Recharts necesita colores reales en atributos SVG: leemos los tokens CSS y
 *  los volvemos a leer si cambia el tema del sistema. */
function useTheme(): Theme | null {
  const [theme, setTheme] = useState<Theme | null>(null);
  useEffect(() => {
    const read = () => {
      const style = getComputedStyle(document.documentElement);
      setTheme(
        Object.fromEntries(
          TOKENS.map((t) => [t, style.getPropertyValue(`--${t}`).trim()]),
        ) as Theme,
      );
    };
    read();
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    media.addEventListener("change", read);
    return () => media.removeEventListener("change", read);
  }, []);
  return theme;
}

export function ChartCard({
  chart,
  selected,
  onToggle,
}: {
  chart: RenderedChart;
  selected?: boolean;
  onToggle?: () => void;
}) {
  const { spec, data, error } = chart;
  const wide = spec.chart_type === "table" || spec.chart_type === "line";
  const compact = spec.chart_type === "kpi";

  return (
    <section
      className={`rounded-xl border bg-surface p-4 ${
        selected ? "border-accent ring-1 ring-accent" : "border-line"
      } ${wide ? "md:col-span-2" : ""} ${compact ? "" : "min-h-72"}`}
    >
      <header className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="font-medium">{spec.title}</h3>
          {onToggle && <p className="mt-0.5 text-xs text-muted">{spec.reason}</p>}
        </div>
        {onToggle && (
          <label className="flex shrink-0 cursor-pointer items-center gap-1.5 text-xs text-ink-2">
            <input type="checkbox" checked={selected} onChange={onToggle} />
            Incluir
          </label>
        )}
      </header>
      {error || !data ? (
        <p className="text-sm text-danger">{error ?? "Sin datos"}</p>
      ) : (
        <>
          <ChartBody chart={chart} data={data} />
          {"notes" in data && data.notes && data.notes.length > 0 && (
            <ul className="mt-3 space-y-0.5 text-xs text-muted">
              {data.notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}

/** Qué mide exactamente el eje Y / la cifra, en palabras. */
function describeMeasure(spec: RenderedChart["spec"]): string {
  const unit = spec.group_by ? `${spec.group_by}s distintos` : "Registros";
  if (spec.aggregation === "count" || !spec.y) {
    return spec.per_day ? `${unit} por día (promedio)` : unit;
  }
  if (spec.per_day) return `Promedio diario de ${spec.y}`;
  if (spec.aggregation === "mean") {
    return spec.group_by ? `Promedio por ${spec.group_by} de ${spec.y}` : `Promedio de ${spec.y}`;
  }
  return `Total de ${spec.y}`;
}

function ChartBody({ chart, data }: { chart: RenderedChart; data: ChartData }) {
  const theme = useTheme();
  const { spec } = chart;

  if ("value" in data) {
    return (
      <div>
        <p className="text-3xl font-semibold">{formatNumber(data.value)}</p>
        <p className="mt-1 text-xs text-muted">{describeMeasure(spec)}</p>
      </div>
    );
  }
  if ("rows" in data) return <DataTable data={data} />;
  if (!theme) return <div className="h-60" />;
  if (data.points.length === 0) return <p className="text-sm text-muted">Sin datos</p>;

  const yLabel = describeMeasure(spec);
  const axis = {
    stroke: theme.axis,
    tick: { fill: theme["text-muted"], fontSize: 12 },
    tickLine: false,
  };
  const tooltip = (
    <Tooltip
      cursor={{ fill: theme.grid, stroke: theme.axis }}
      content={({ active, payload, label }) => {
        const point = payload?.[0]?.payload as Point | undefined;
        if (!active || !point) return null;
        return (
          <div
            style={{
              background: theme.surface,
              border: `1px solid ${theme.grid}`,
              borderRadius: 8,
              padding: "6px 10px",
              fontSize: 12,
            }}
          >
            <div style={{ color: theme["text-secondary"] }}>{label ?? point.x}</div>
            <div style={{ color: theme["text-primary"] }}>
              {yLabel}: <strong>{formatNumber(point.y)}</strong>
            </div>
            {point.partial && (
              <div style={{ color: theme["text-muted"] }}>Periodo incompleto en los datos</div>
            )}
          </div>
        );
      }}
    />
  );
  const grid = <CartesianGrid stroke={theme.grid} vertical={false} />;
  const yAxis = <YAxis {...axis} axisLine={false} width={56} tickFormatter={(v) => formatNumber(v, true)} />;
  const frame = (child: ReactNode) => (
    <div className="h-60">
      <ResponsiveContainer width="100%" height="100%">
        {child as React.ReactElement}
      </ResponsiveContainer>
    </div>
  );
  const points = data.points as Point[];

  switch (spec.chart_type) {
    case "line": {
      // Tramo sólido para periodos completos y punteado hacia los incompletos, para que
      // una semana a medias no se lea como una caída real.
      const series = points.map((p, i) => ({
        ...p,
        full: p.partial ? null : p.y,
        partialY:
          p.partial || points[i - 1]?.partial || points[i + 1]?.partial ? p.y : null,
      }));
      const hasPartial = points.some((p) => p.partial);
      return frame(
        <LineChart data={series} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
          {grid}
          <XAxis dataKey="x" {...axis} minTickGap={24} />
          {yAxis}
          {tooltip}
          <Line
            dataKey="full"
            type="linear"
            stroke={theme["series-1"]}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 5, stroke: theme.surface, strokeWidth: 2 }}
            isAnimationActive={false}
          />
          {hasPartial && (
            <Line
              dataKey="partialY"
              type="linear"
              stroke={theme["series-1"]}
              strokeWidth={2}
              strokeDasharray="4 4"
              dot={(props: { cx?: number; cy?: number; index?: number }) => {
                const p = series[props.index ?? 0];
                if (!p?.partial || props.cx == null || props.cy == null) {
                  return <g key={props.index} />;
                }
                return (
                  <circle
                    key={props.index}
                    cx={props.cx}
                    cy={props.cy}
                    r={4}
                    fill={theme.surface}
                    stroke={theme["series-1"]}
                    strokeWidth={2}
                  />
                );
              }}
              activeDot={false}
              isAnimationActive={false}
            />
          )}
        </LineChart>,
      );
    }
    case "bar":
      return frame(
        <BarChart data={points} margin={{ top: 8, right: 8, left: 0, bottom: 0 }} barCategoryGap={2}>
          {grid}
          <XAxis dataKey="x" {...axis} interval={0} tick={<TruncatedTick fill={theme["text-muted"]} />} height={40} />
          {yAxis}
          {tooltip}
          <Bar dataKey="y" fill={theme["series-1"]} radius={[4, 4, 0, 0]} maxBarSize={48} />
        </BarChart>,
      );
    case "pie": {
      const colors = [1, 2, 3, 4, 5, 6].map((i) => theme[`series-${i}` as keyof Theme]);
      return frame(
        <PieChart>
          {tooltip}
          <Pie
            data={points}
            dataKey="y"
            nameKey="x"
            innerRadius="55%"
            outerRadius="85%"
            stroke={theme.surface}
            strokeWidth={2}
          >
            {points.map((p, i) => (
              <Cell key={String(p.x)} fill={colors[i % colors.length]} />
            ))}
          </Pie>
          <Legend
            layout="vertical"
            align="right"
            verticalAlign="middle"
            iconType="circle"
            formatter={(value) => (
              <span style={{ color: theme["text-secondary"], fontSize: 12 }}>{value}</span>
            )}
          />
        </PieChart>,
      );
    }
    case "scatter":
      return frame(
        <ScatterChart margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
          <CartesianGrid stroke={theme.grid} />
          <XAxis dataKey="x" type="number" name={spec.x ?? ""} {...axis} tickFormatter={(v) => formatNumber(v, true)} />
          <YAxis dataKey="y" type="number" name={spec.y ?? ""} {...axis} axisLine={false} width={56} tickFormatter={(v) => formatNumber(v, true)} />
          <Tooltip
            cursor={{ stroke: theme.axis }}
            contentStyle={{ background: theme.surface, border: `1px solid ${theme.grid}`, borderRadius: 8, fontSize: 12 }}
            formatter={(v, name) => [formatNumber(v), name]}
          />
          <Scatter data={points} fill={theme["series-1"]} fillOpacity={0.7} />
        </ScatterChart>,
      );
    default:
      return null;
  }
}

function TruncatedTick(props: { x?: number; y?: number; payload?: { value: unknown }; fill: string }) {
  const text = String(props.payload?.value ?? "");
  const label = text.length > 12 ? `${text.slice(0, 11)}…` : text;
  return (
    <text x={props.x} y={(props.y ?? 0) + 12} textAnchor="middle" fill={props.fill} fontSize={12}>
      <title>{text}</title>
      {label}
    </text>
  );
}

function DataTable({ data }: { data: { columns: string[]; rows: unknown[][]; total_rows: number } }) {
  return (
    <div>
      <div className="max-h-72 overflow-auto rounded-lg border border-line">
        <table className="w-full text-left text-sm tabular-nums">
          <thead className="sticky top-0 bg-surface text-xs text-muted">
            <tr>
              {data.columns.map((c) => (
                <th key={c} className="border-b border-line px-3 py-2 font-medium whitespace-nowrap">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row, i) => (
              <tr key={i} className="border-b border-line last:border-0">
                {row.map((v, j) => (
                  <td key={j} className="px-3 py-1.5 whitespace-nowrap">
                    {formatNumber(v)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-muted">
        Mostrando {data.rows.length} de {formatNumber(data.total_rows)} filas
      </p>
    </div>
  );
}
