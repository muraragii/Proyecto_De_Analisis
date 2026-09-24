"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ChartEditor } from "@/components/ChartEditor";
import { ChartGrid } from "@/components/ChartGrid";
import { Insights } from "@/components/Insights";
import { api, type ColumnProfile, type Dashboard, type RenderedChart } from "@/lib/api";

export default function DashboardPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  // Modo edición: copia de trabajo de los gráficos; se guarda solo al confirmar.
  const [draft, setDraft] = useState<RenderedChart[] | null>(null);
  const [columns, setColumns] = useState<ColumnProfile[]>([]);
  const [editing, setEditing] = useState<{ index: number | null } | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.dashboard(id).then(setDashboard).catch((e) => setError(e.message));
  }, [id]);

  if (error) return <p className="text-danger">{error}</p>;
  if (!dashboard) return <p className="text-muted">Cargando…</p>;

  const shareUrl = dashboard.share_token
    ? `${window.location.origin}/share/${dashboard.share_token}`
    : null;

  async function toggleShare() {
    const updated = dashboard!.share_token ? await api.unshare(id) : await api.share(id);
    setDashboard((d) => d && { ...d, share_token: updated.share_token });
    setCopied(false);
  }

  async function copy() {
    if (!shareUrl) return;
    await navigator.clipboard.writeText(shareUrl);
    setCopied(true);
  }

  async function remove() {
    await api.deleteDashboard(id);
    router.push("/");
  }

  async function startEditing() {
    try {
      const dataset = await api.dataset(dashboard!.dataset_id);
      setColumns(dataset.profile?.columns ?? []);
      setDraft(dashboard!.charts ?? []);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function saveChanges() {
    if (!draft) return;
    setSaving(true);
    try {
      await api.updateDashboard(id, { charts: draft.map((c) => c.spec) });
      // Se recarga para recalcular gráficos y hallazgos con los datos actuales.
      setDashboard(await api.dashboard(id));
      setDraft(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  const charts = draft ?? dashboard.charts ?? [];

  return (
    <div className="space-y-6">
      <section className="flex flex-wrap items-start justify-between gap-4">
        <h1 className="text-2xl font-semibold">{dashboard.title}</h1>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          {draft ? (
            <>
              <button
                onClick={() => setEditing({ index: null })}
                className="rounded-lg border border-accent px-3 py-2 font-medium text-accent"
              >
                + Crear gráfico
              </button>
              <button onClick={() => setDraft(null)} className="rounded-lg border border-line bg-surface px-3 py-2">
                Cancelar
              </button>
              <button
                onClick={saveChanges}
                disabled={saving || draft.length === 0}
                className="rounded-lg bg-accent px-3 py-2 font-medium text-white disabled:opacity-50"
              >
                {saving ? "Guardando…" : "Guardar cambios"}
              </button>
            </>
          ) : (
            <>
              <button onClick={startEditing} className="rounded-lg border border-line bg-surface px-3 py-2">
                ✏️ Editar gráficos
              </button>
              <button onClick={toggleShare} className="rounded-lg border border-line bg-surface px-3 py-2">
                {shareUrl ? "Dejar de compartir" : "Compartir por enlace"}
              </button>
              <button onClick={remove} className="rounded-lg border border-line bg-surface px-3 py-2 text-danger">
                Eliminar
              </button>
            </>
          )}
        </div>
      </section>
      {shareUrl && !draft && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-line bg-surface px-3 py-2 text-sm">
          <span className="text-ink-2">Enlace público (solo lectura):</span>
          <code className="min-w-0 flex-1 truncate">{shareUrl}</code>
          <button onClick={copy} className="font-medium text-accent">
            {copied ? "Copiado" : "Copiar"}
          </button>
        </div>
      )}
      {draft && (
        <p className="rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink-2">
          Modo edición: ajusta, agrega o quita gráficos. Los cambios se aplican al guardar
          {shareUrl ? ", también en el enlace compartido" : ""}.
        </p>
      )}
      {!draft && <Insights insights={dashboard.insights ?? []} />}
      <ChartGrid
        charts={charts}
        onEdit={draft ? (i) => setEditing({ index: i }) : undefined}
        onRemove={draft ? (i) => setDraft((d) => d && d.filter((_, j) => j !== i)) : undefined}
      />
      {editing && draft && (
        <ChartEditor
          datasetId={dashboard.dataset_id}
          columns={columns}
          initial={editing.index === null ? undefined : draft[editing.index].spec}
          onClose={() => setEditing(null)}
          onSave={(chart) => {
            const index = editing.index;
            setDraft((d) =>
              !d ? d : index === null ? [...d, chart] : d.map((c, i) => (i === index ? chart : c)),
            );
            setEditing(null);
          }}
        />
      )}
    </div>
  );
}
