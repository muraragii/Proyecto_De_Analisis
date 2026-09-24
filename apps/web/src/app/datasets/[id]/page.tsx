"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ChartGrid } from "@/components/ChartGrid";
import {
  api,
  formatNumber,
  type Dataset,
  type Industry,
  type Recommendations,
  type SemanticType,
} from "@/lib/api";

const TYPE_LABEL: Record<SemanticType, string> = {
  numeric: "Numérica",
  categorical: "Categórica",
  datetime: "Fecha",
  boolean: "Sí/No",
  identifier: "Identificador",
  text: "Texto libre",
};

export default function DatasetPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [industries, setIndustries] = useState<Industry[]>([]);
  const [industry, setIndustry] = useState("auto");
  const [rec, setRec] = useState<Recommendations | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [title, setTitle] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.dataset(id), api.industries()])
      .then(([ds, inds]) => {
        setDataset(ds);
        setIndustries(inds);
        setTitle(`Dashboard de ${ds.name}`);
      })
      .catch((e) => setError(e.message));
  }, [id]);

  useEffect(() => {
    let stale = false;
    api
      .recommendations(id, industry)
      .then((r) => {
        if (stale) return;
        setRec(r);
        setSelected(new Set(r.charts.map((_, i) => i)));
      })
      .catch((e) => !stale && setError(e.message));
    return () => {
      stale = true;
    };
  }, [id, industry]);

  async function save() {
    if (!rec) return;
    setSaving(true);
    try {
      const dashboard = await api.createDashboard({
        dataset_id: id,
        title,
        industry: rec.industry,
        charts: rec.charts.filter((_, i) => selected.has(i)).map((c) => c.spec),
      });
      router.push(`/dashboards/${dashboard.id}`);
    } catch (e) {
      setError((e as Error).message);
      setSaving(false);
    }
  }

  if (error) return <p className="text-danger">{error}</p>;
  if (!dataset) return <p className="text-muted">Cargando…</p>;

  const detected = industries.find((i) => i.id === rec?.detected_industry);

  return (
    <div className="space-y-8">
      <section>
        <h1 className="text-2xl font-semibold">{dataset.filename}</h1>
        <p className="mt-1 text-ink-2">
          {formatNumber(dataset.n_rows)} filas · {dataset.n_cols} columnas
          {detected && ` · Parece un negocio de tipo ${detected.name}`}
        </p>
      </section>

      <details className="rounded-xl border border-line bg-surface">
        <summary className="cursor-pointer px-4 py-3 font-medium">Perfil de columnas</summary>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs text-muted">
              <tr>
                <th className="px-4 py-2 font-medium">Columna</th>
                <th className="px-4 py-2 font-medium">Tipo detectado</th>
                <th className="px-4 py-2 font-medium tabular-nums">Valores únicos</th>
                <th className="px-4 py-2 font-medium tabular-nums">Nulos</th>
              </tr>
            </thead>
            <tbody>
              {dataset.profile?.columns.map((c) => (
                <tr key={c.name} className="border-t border-line">
                  <td className="px-4 py-2">{c.name}</td>
                  <td className="px-4 py-2">{TYPE_LABEL[c.semantic_type]}</td>
                  <td className="px-4 py-2 tabular-nums">{formatNumber(c.n_unique)}</td>
                  <td className="px-4 py-2 tabular-nums">{Math.round(c.null_ratio * 100)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>

      <section className="flex flex-wrap items-end gap-4">
        <label className="text-sm">
          <span className="mb-1 block text-ink-2">Tipo de negocio</span>
          <select
            value={industry}
            onChange={(e) => {
              setRec(null);
              setIndustry(e.target.value);
            }}
            className="rounded-lg border border-line bg-surface px-3 py-2"
          >
            <option value="auto">Detectar automáticamente</option>
            {industries.map((i) => (
              <option key={i.id} value={i.id}>
                {i.name}
              </option>
            ))}
            <option value="none">Genérico (sin plantilla)</option>
          </select>
        </label>
        <label className="min-w-64 flex-1 text-sm">
          <span className="mb-1 block text-ink-2">Nombre del dashboard</span>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="w-full rounded-lg border border-line bg-surface px-3 py-2"
          />
        </label>
        <button
          onClick={save}
          disabled={saving || selected.size === 0 || !title.trim()}
          className="rounded-lg bg-accent px-4 py-2 font-medium text-white disabled:opacity-50"
        >
          {saving ? "Guardando…" : `Guardar dashboard (${selected.size})`}
        </button>
      </section>

      {rec ? (
        <ChartGrid
          charts={rec.charts}
          isSelected={(i) => selected.has(i)}
          onToggle={(i) =>
            setSelected((prev) => {
              const next = new Set(prev);
              if (next.has(i)) next.delete(i);
              else next.add(i);
              return next;
            })
          }
        />
      ) : (
        <p className="text-muted">Generando recomendaciones…</p>
      )}
    </div>
  );
}
