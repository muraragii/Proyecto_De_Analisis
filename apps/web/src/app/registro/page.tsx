"use client";

import Link from "next/link";
import { AuthForm, Field } from "@/components/AuthForm";
import { auth } from "@/lib/api";

export default function RegisterPage() {
  return (
    <AuthForm
      title="Crea tu cuenta"
      subtitle="Gratis. Sube tus datos y obtén tus primeros gráficos en minutos."
      submitLabel="Crear cuenta"
      onSubmit={(f) =>
        auth.register({
          name: String(f.get("name")),
          email: String(f.get("email")),
          password: String(f.get("password")),
          organization_name: String(f.get("organization_name")),
        })
      }
      footer={
        <>
          ¿Ya tienes cuenta?{" "}
          <Link href="/login" className="font-medium text-accent">
            Inicia sesión
          </Link>
        </>
      }
    >
      <Field label="Tu nombre" name="name" autoComplete="name" />
      <Field
        label="Nombre de tu negocio"
        name="organization_name"
        autoComplete="organization"
        hint="Podrás invitar a tu equipo más adelante."
      />
      <Field label="Correo" name="email" type="email" autoComplete="email" />
      <Field
        label="Contraseña"
        name="password"
        type="password"
        autoComplete="new-password"
        minLength={8}
        hint="Mínimo 8 caracteres."
      />
    </AuthForm>
  );
}
