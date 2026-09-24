"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ChartGrid } from "@/components/ChartGrid";
import { api, type Dashboard } from "@/lib/api";

export default function DashboardPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

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

  return (
    <div className="space-y-6">
      <section className="flex flex-wrap items-start justify-between gap-4">
        <h1 className="text-2xl font-semibold">{dashboard.title}</h1>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <button onClick={toggleShare} className="rounded-lg border border-line bg-surface px-3 py-2">
            {shareUrl ? "Dejar de compartir" : "Compartir por enlace"}
          </button>
          <button onClick={remove} className="rounded-lg border border-line bg-surface px-3 py-2 text-danger">
            Eliminar
          </button>
        </div>
      </section>
      {shareUrl && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-line bg-surface px-3 py-2 text-sm">
          <span className="text-ink-2">Enlace público (solo lectura):</span>
          <code className="min-w-0 flex-1 truncate">{shareUrl}</code>
          <button onClick={copy} className="font-medium text-accent">
            {copied ? "Copiado" : "Copiar"}
          </button>
        </div>
      )}
      <ChartGrid charts={dashboard.charts ?? []} />
    </div>
  );
}
