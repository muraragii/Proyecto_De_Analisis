"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, formatNumber, type Dashboard, type Dataset } from "@/lib/api";

export default function Home() {
  const router = useRouter();
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [dashboards, setDashboards] = useState<Dashboard[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.datasets(), api.dashboards()])
      .then(([ds, dbs]) => {
        setDatasets(ds);
        setDashboards(dbs);
      })
      .catch((e) => setError(`No se pudo conectar con la API: ${e.message}`));
  }, []);

  async function onFile(file: File | undefined) {
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const dataset = await api.upload(file);
      router.push(`/datasets/${dataset.id}`);
    } catch (e) {
      setError((e as Error).message);
      setUploading(false);
    }
  }

  return (
    <div className="space-y-10">
      <section>
        <h1 className="text-2xl font-semibold">Sube tus datos</h1>
        <p className="mt-1 text-ink-2">
          Carga un CSV o Excel y te sugerimos los gráficos que tu negocio necesita.
        </p>
        <label
          className="mt-4 flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed border-line bg-surface px-6 py-12 text-center hover:border-accent"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            onFile(e.dataTransfer.files[0]);
          }}
        >
          <span className="font-medium">
            {uploading ? "Analizando archivo…" : "Arrastra un archivo aquí o haz clic para elegirlo"}
          </span>
          <span className="mt-1 text-sm text-muted">CSV, XLSX o XLS · hasta 50 MB</span>
          <input
            type="file"
            accept=".csv,.txt,.xlsx,.xls"
            className="hidden"
            disabled={uploading}
            onChange={(e) => onFile(e.target.files?.[0])}
          />
        </label>
        {error && <p className="mt-3 text-sm text-danger">{error}</p>}
      </section>

      <div className="grid gap-8 md:grid-cols-2">
        <section>
          <h2 className="mb-3 font-semibold">Dashboards</h2>
          {dashboards.length === 0 ? (
            <p className="text-sm text-muted">Aún no guardas ningún dashboard.</p>
          ) : (
            <ul className="divide-y divide-line rounded-xl border border-line bg-surface">
              {dashboards.map((d) => (
                <li key={d.id}>
                  <Link href={`/dashboards/${d.id}`} className="flex justify-between px-4 py-3 hover:bg-page">
                    <span>{d.title}</span>
                    {d.share_token && <span className="text-xs text-muted">Compartido</span>}
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>
        <section>
          <h2 className="mb-3 font-semibold">Datos cargados</h2>
          {datasets.length === 0 ? (
            <p className="text-sm text-muted">Todavía no hay archivos.</p>
          ) : (
            <ul className="divide-y divide-line rounded-xl border border-line bg-surface">
              {datasets.map((d) => (
                <li key={d.id}>
                  <Link href={`/datasets/${d.id}`} className="flex justify-between gap-4 px-4 py-3 hover:bg-page">
                    <span className="truncate">{d.filename}</span>
                    <span className="shrink-0 text-xs text-muted">
                      {formatNumber(d.n_rows)} filas · {d.n_cols} columnas
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
