"use client";

import { type FormEvent, useState } from "react";

import { ApiError, changePassword } from "./api";

type Props = {
  token: string;
  onChanged: (nextToken: string) => void;
};

export function PasswordChangeOperations({ token, onChanged }: Props) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (newPassword !== confirmation) {
      setError("La confirmación no coincide con la nueva contraseña.");
      return;
    }
    if (!window.confirm("¿Confirmas el cambio de contraseña? Las demás sesiones activas se cerrarán.")) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const response = await changePassword(token, currentPassword, newPassword);
      onChanged(response.access_token);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmation("");
      setNotice("Contraseña actualizada. Las sesiones anteriores ya no pueden usarse.");
    } catch (cause) {
      setError(messageFor(cause, "No fue posible cambiar la contraseña."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="beta-setup password-change" aria-labelledby="password-change-title">
      <p className="eyebrow">SEGURIDAD DE LA CUENTA</p>
      <h1 id="password-change-title">Actualiza tu contraseña.</h1>
      <p className="beta-lead">Las cuentas con clave temporal deben cambiarla antes de incorporar información de su empresa.</p>
      <form className="operations-form beta-form" onSubmit={submit}>
        <label>Contraseña actual<input type="password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} autoComplete="current-password" minLength={8} maxLength={128} required /></label>
        <label>Nueva contraseña<input type="password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} autoComplete="new-password" minLength={12} maxLength={128} required /></label>
        <label>Confirma la nueva contraseña<input type="password" value={confirmation} onChange={(event) => setConfirmation(event.target.value)} autoComplete="new-password" minLength={12} maxLength={128} required /></label>
        <p className="beta-note">Usa al menos 12 caracteres, una mayúscula, una minúscula y un número. No reutilices la clave temporal.</p>
        {error ? <p className="form-error" role="alert">{error}</p> : null}
        {notice ? <p className="initial-import-result" role="status">{notice}</p> : null}
        <button className="secondary-action" disabled={busy}>{busy ? "Actualizando…" : "Cambiar contraseña"}</button>
      </form>
    </section>
  );
}

function messageFor(cause: unknown, fallback: string) {
  return cause instanceof ApiError || cause instanceof Error ? cause.message : fallback;
}
