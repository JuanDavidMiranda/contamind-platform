"use client";

import { type FormEvent, useState } from "react";

import { ApiError, createBetaAccess } from "./api";
import type { BetaAccess } from "./types";

type Props = { token: string };

export function BetaAccessOperations({ token }: Props) {
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [temporaryPassword, setTemporaryPassword] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<BetaAccess | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!confirmed) return;
    if (!window.confirm("¿Confirmas que crearás este acceso cerrado de beta y compartirás la contraseña temporal por un canal seguro?")) return;
    setBusy(true);
    setError(null);
    setCreated(null);
    try {
      const result = await createBetaAccess(token, {
        full_name: fullName.trim(),
        email: email.trim(),
        temporary_password: temporaryPassword,
      });
      setCreated(result);
      setFullName("");
      setEmail("");
      setTemporaryPassword("");
      setConfirmed(false);
    } catch (cause) {
      setError(messageFor(cause, "No fue posible crear el acceso de prueba."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="beta-setup beta-access" aria-labelledby="beta-access-title">
      <p className="eyebrow">ADMINISTRACIÓN DE BETA</p>
      <h1 id="beta-access-title">Crea un acceso privado para el cliente.</h1>
      <p className="beta-lead">La cuenta se crea sin empresa asignada: la persona invitada será propietaria de la primera empresa que configure. Esta pantalla nunca muestra ni conserva la contraseña después de enviarla.</p>
      <form className="operations-form beta-form" onSubmit={submit}>
        <label>Nombre completo<input value={fullName} onChange={(event) => setFullName(event.target.value)} autoComplete="name" minLength={2} maxLength={255} required /></label>
        <label>Correo electrónico<input type="email" value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="email" maxLength={255} required /></label>
        <label>Contraseña temporal<input type="password" value={temporaryPassword} onChange={(event) => setTemporaryPassword(event.target.value)} autoComplete="new-password" minLength={12} maxLength={128} required /></label>
        <p className="beta-note">Exige una mayúscula, una minúscula y un número. Compártela por un canal seguro y pide que la cambie en su primera sesión.</p>
        <label className="check-line confirm-line"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} required />Confirmo que tengo autorización para crear este acceso y que no enviaré la contraseña por canales inseguros.</label>
        {error ? <p className="form-error" role="alert">{error}</p> : null}
        <button className="secondary-action" disabled={!confirmed || busy}>{busy ? "Creando acceso…" : "Crear acceso de beta"}</button>
      </form>
      {created ? <section className="initial-import-result" role="status"><b>Acceso creado para {created.full_name}.</b> Comparte con la persona invitada el correo {created.email} y la contraseña temporal que definiste; deberá cambiarla antes de cargar información.</section> : null}
    </section>
  );
}

function messageFor(cause: unknown, fallback: string) {
  return cause instanceof ApiError || cause instanceof Error ? cause.message : fallback;
}
