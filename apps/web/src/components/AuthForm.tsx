"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent, type ReactNode } from "react";
import { useAuth } from "@/components/AuthProvider";
import type { Me } from "@/lib/api";

/** Destino tras iniciar sesión: solo rutas internas, para no permitir redirecciones abiertas. */
function nextPath(): string {
  const next = new URLSearchParams(window.location.search).get("next");
  return next?.startsWith("/") && !next.startsWith("//") ? next : "/";
}

export function AuthForm({
  title,
  subtitle,
  submitLabel,
  onSubmit,
  footer,
  children,
}: {
  title: string;
  subtitle: string;
  submitLabel: string;
  onSubmit: (form: FormData) => Promise<Me>;
  footer: ReactNode;
  children: ReactNode;
}) {
  const router = useRouter();
  const { signedIn } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handle(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      signedIn(await onSubmit(new FormData(e.currentTarget)));
      router.replace(nextPath());
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-sm pt-8">
      <h1 className="text-2xl font-semibold">{title}</h1>
      <p className="mt-1 text-ink-2">{subtitle}</p>
      <form onSubmit={handle} className="mt-6 space-y-4 rounded-xl border border-line bg-surface p-6">
        {children}
        {error && (
          <p role="alert" className="text-sm text-danger">
            {error}
          </p>
        )}
        <button
          type="submit"
          disabled={busy}
          className="w-full rounded-lg bg-accent px-4 py-2 font-medium text-white disabled:opacity-50"
        >
          {busy ? "Un momento…" : submitLabel}
        </button>
      </form>
      <p className="mt-4 text-center text-sm text-ink-2">{footer}</p>
    </div>
  );
}

export function Field({
  label,
  name,
  type = "text",
  autoComplete,
  hint,
  minLength,
}: {
  label: string;
  name: string;
  type?: string;
  autoComplete?: string;
  hint?: string;
  minLength?: number;
}) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block text-ink-2">{label}</span>
      <input
        name={name}
        type={type}
        required
        minLength={minLength}
        autoComplete={autoComplete}
        className="w-full rounded-lg border border-line bg-page px-3 py-2"
      />
      {hint && <span className="mt-1 block text-xs text-muted">{hint}</span>}
    </label>
  );
}
