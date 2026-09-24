"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { ChartGrid } from "@/components/ChartGrid";
import { Insights } from "@/components/Insights";
import { api, type Dashboard } from "@/lib/api";

export default function SharedDashboardPage() {
  const { token } = useParams<{ token: string }>();
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.publicDashboard(token).then(setDashboard).catch((e) => setError(e.message));
  }, [token]);

  if (error) return <p className="text-danger">{error}</p>;
  if (!dashboard) return <p className="text-muted">Cargando…</p>;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">{dashboard.title}</h1>
      <Insights insights={dashboard.insights ?? []} />
      <ChartGrid charts={dashboard.charts ?? []} />
    </div>
  );
}
