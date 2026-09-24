"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { auth, SESSION_EXPIRED_EVENT, type Me } from "@/lib/api";

const PUBLIC_PREFIXES = ["/login", "/registro", "/share"];
const GUEST_ONLY = ["/login", "/registro"];

type Status = "loading" | "in" | "out";

interface AuthState {
  me: Me | null;
  signedIn: (me: Me) => void;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth debe usarse dentro de <AuthProvider>");
  return ctx;
}

const isPublic = (path: string) => PUBLIC_PREFIXES.some((p) => path.startsWith(p));

export function AuthProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [me, setMe] = useState<Me | null>(null);
  const [status, setStatus] = useState<Status>("loading");

  useEffect(() => {
    auth
      .me()
      .then((m) => {
        setMe(m);
        setStatus("in");
      })
      .catch(() => setStatus("out"));

    const expired = () => {
      setMe(null);
      setStatus("out");
    };
    window.addEventListener(SESSION_EXPIRED_EVENT, expired);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, expired);
  }, []);

  useEffect(() => {
    if (status === "out" && !isPublic(pathname)) {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    } else if (status === "in" && GUEST_ONLY.includes(pathname)) {
      router.replace("/");
    }
  }, [status, pathname, router]);

  const state: AuthState = {
    me,
    signedIn: (m) => {
      setMe(m);
      setStatus("in");
    },
    logout: async () => {
      await auth.logout().catch(() => undefined);
      setMe(null);
      setStatus("out");
    },
  };

  const blocked = !isPublic(pathname) && status !== "in";

  return (
    <AuthContext.Provider value={state}>
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
          <Link href="/" className="font-semibold">
            Proyecto Análisis
          </Link>
          {me ? (
            <div className="ml-auto flex items-center gap-4 text-sm">
              <span className="text-ink-2">
                {me.organization.name}
                <span className="text-muted"> · {me.user.name}</span>
              </span>
              <button onClick={state.logout} className="text-accent">
                Cerrar sesión
              </button>
            </div>
          ) : (
            <span className="text-sm text-muted">Visualizaciones para tu negocio</span>
          )}
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8">
        {blocked ? <p className="text-muted">Cargando…</p> : children}
      </main>
    </AuthContext.Provider>
  );
}
