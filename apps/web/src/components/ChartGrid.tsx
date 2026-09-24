import { ChartCard } from "@/components/ChartCard";
import type { RenderedChart } from "@/lib/api";

/** KPIs en una fila arriba; el resto de gráficos en una rejilla de dos columnas. */
export function ChartGrid({
  charts,
  isSelected,
  onToggle,
  onEdit,
  onRemove,
}: {
  charts: RenderedChart[];
  isSelected?: (index: number) => boolean;
  onToggle?: (index: number) => void;
  onEdit?: (index: number) => void;
  onRemove?: (index: number) => void;
}) {
  const indexed = charts.map((chart, index) => ({ chart, index }));
  const kpis = indexed.filter((c) => c.chart.spec.chart_type === "kpi");
  const others = indexed.filter((c) => c.chart.spec.chart_type !== "kpi");
  const card = ({ chart, index }: { chart: RenderedChart; index: number }) => (
    <ChartCard
      key={index}
      chart={chart}
      selected={isSelected?.(index)}
      onToggle={onToggle && (() => onToggle(index))}
      onEdit={onEdit && (() => onEdit(index))}
      onRemove={onRemove && (() => onRemove(index))}
    />
  );

  return (
    <div className="space-y-4">
      {kpis.length > 0 && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">{kpis.map(card)}</div>
      )}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">{others.map(card)}</div>
    </div>
  );
}
