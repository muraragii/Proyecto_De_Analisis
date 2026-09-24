"use client";

import Link from "next/link";
import { AuthForm, Field } from "@/components/AuthForm";
import { auth } from "@/lib/api";

export default function LoginPage() {
  return (
    <AuthForm
      title="Inicia sesión"
      subtitle="Accede a los dashboards de tu negocio."
      submitLabel="Entrar"
      onSubmit={(f) => auth.login(String(f.get("email")), String(f.get("password")))}
      footer={
        <>
          ¿No tienes cuenta?{" "}
          <Link href="/registro" className="font-medium text-accent">
            Crear cuenta
          </Link>
        </>
      }
    >
      <Field label="Correo" name="email" type="email" autoComplete="email" />
      <Field label="Contraseña" name="password" type="password" autoComplete="current-password" />
    </AuthForm>
  );
}
