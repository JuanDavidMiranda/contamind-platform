"use client";

import { type FormEvent, useCallback, useEffect, useState } from "react";

import {
  ApiError,
  bankAccounts,
  bankBalanceSnapshots,
  bankTransactions,
  createBankAccount,
  createBankBalanceSnapshot,
  importBankStatement,
  reviewBankTransaction,
} from "./api";
import type {
  BankAccount,
  BankBalanceSnapshot,
  BankImportResult,
  BankReviewAction,
  BankTransaction,
  BankTransactionStatus,
} from "./types";


type Props = {
  token: string;
  companyId: string;
  companyName: string;
  enabled: boolean;
};

const statusLabels: Record<BankTransactionStatus, string> = {
  pending: "Pendiente",
  suggested: "Coincidencia sugerida",
  reconciled: "Conciliado",
  dismissed: "Sugerencia descartada",
  excluded: "Excluido",
};

export function BankReconciliationOperations({ token, companyId, companyName, enabled }: Props) {
  const [accounts, setAccounts] = useState<BankAccount[]>([]);
  const [transactions, setTransactions] = useState<BankTransaction[]>([]);
  const [balanceSnapshots, setBalanceSnapshots] = useState<BankBalanceSnapshot[]>([]);
  const [total, setTotal] = useState(0);
  const [canManage, setCanManage] = useState(false);
  const [canConfigure, setCanConfigure] = useState(false);
  const [selectedAccountId, setSelectedAccountId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [importResult, setImportResult] = useState<BankImportResult | null>(null);

  const load = useCallback(async () => {
    if (!enabled) {
      setAccounts([]);
      setTransactions([]);
      setBalanceSnapshots([]);
      setTotal(0);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const [accountPage, transactionPage, balancePage] = await Promise.all([
        bankAccounts(token, companyId),
        bankTransactions(token, companyId, { limit: 100 }),
        bankBalanceSnapshots(token, companyId),
      ]);
      setAccounts(accountPage.accounts);
      setTransactions(transactionPage.items);
      setBalanceSnapshots(balancePage.snapshots);
      setTotal(transactionPage.total);
      setCanManage(accountPage.can_manage && transactionPage.can_manage && balancePage.can_manage);
      setCanConfigure(accountPage.can_configure);
      setSelectedAccountId((current) => (
        accountPage.accounts.some((account) => account.id === current)
          ? current
          : accountPage.accounts.find((account) => account.status === "active")?.id || ""
      ));
    } catch (cause) {
      setError(messageFor(cause, "No fue posible cargar la conciliación operativa."));
    } finally {
      setLoading(false);
    }
  }, [companyId, enabled, token]);

  useEffect(() => {
    let disposed = false;
    void Promise.resolve().then(() => {
      if (!disposed) return load();
    });
    return () => { disposed = true; };
  }, [load]);

  if (!enabled) {
    return (
      <section className="bank-operations unavailable">
        <p className="eyebrow">CONCILIACIÓN OPERATIVA</p>
        <h2>La empresa está desactivada.</h2>
        <p>Reactiva {companyName} para importar y revisar extractos.</p>
      </section>
    );
  }

  async function handleCreated(account: BankAccount) {
    setAccounts((current) => [...current, account]);
    setSelectedAccountId(account.id);
    setCanManage(true);
  }

  async function handleReview(transaction: BankTransaction, action: BankReviewAction) {
    const messages: Record<BankReviewAction, string> = {
      confirm: "¿Confirmas que este movimiento corresponde al pago sugerido?",
      dismiss: "¿Confirmas que deseas descartar esta sugerencia?",
      exclude: "¿Confirmas que este movimiento debe quedar fuera de la conciliación?",
      reopen: "¿Confirmas que deseas reabrir este movimiento para una nueva revisión?",
    };
    if (!window.confirm(messages[action])) return;
    setError(null);
    try {
      await reviewBankTransaction(token, companyId, transaction.id, action);
      await load();
    } catch (cause) {
      setError(messageFor(cause, "No fue posible actualizar el movimiento."));
    }
  }

  return (
    <section className="bank-operations" aria-labelledby="bank-operations-title">
      <header className="operations-heading">
        <div>
          <p className="eyebrow">CONCILIACIÓN OPERATIVA</p>
          <h2 id="bank-operations-title">Extractos y coincidencias</h2>
          <p>{total} movimiento{total === 1 ? "" : "s"} importado{total === 1 ? "" : "s"}.</p>
        </div>
        <button className="quiet-button" type="button" onClick={() => void load()} disabled={loading}>
          {loading ? "Actualizando…" : "Actualizar"}
        </button>
      </header>

      <p className="operations-privacy">
        Esta vista no envía descripciones, referencias ni movimientos al asistente. El chat sólo recibe agregados.
      </p>

      {canManage ? (
        <div className="bank-setup-grid">
          {canConfigure ? (
            <BankAccountForm token={token} companyId={companyId} onCreated={handleCreated} />
          ) : (
            <div className="operations-form bank-account-form">
              <h3>Alias de cuenta</h3>
              <p>Tu rol puede importar y revisar extractos, pero sólo un propietario o administrador puede crear cuentas.</p>
            </div>
          )}
          <BankImportForm
            token={token}
            companyId={companyId}
            accounts={accounts}
            selectedAccountId={selectedAccountId}
            onAccountChange={setSelectedAccountId}
            onImported={async (result) => {
              setImportResult(result);
              await load();
            }}
          />
          <BankBalanceSnapshotForm
            token={token}
            companyId={companyId}
            accounts={accounts}
            selectedAccountId={selectedAccountId}
            onAccountChange={setSelectedAccountId}
            onRecorded={load}
          />
        </div>
      ) : null}

      {accounts.length ? (
        <section className="operations-form bank-balance-summary" aria-label="Cortes bancarios verificados">
          <h3>Cortes bancarios verificados</h3>
          <p>El corte conserva el saldo confirmado por cuenta y fecha; no reemplaza la conciliación.</p>
          {balanceSnapshots.length ? (
            <ul>
              {balanceSnapshots.map((snapshot) => {
                const account = accounts.find((item) => item.id === snapshot.bank_account_id);
                return (
                  <li key={snapshot.id}>
                    <span>{account?.name || "Cuenta"} · {formatDate(snapshot.as_of_date)}</span>
                    <strong>{formatMoney(snapshot.balance, snapshot.currency_code)}</strong>
                  </li>
                );
              })}
            </ul>
          ) : <p className="note-warning">Aún no hay cortes registrados. Tesorería no podrá consolidar el saldo bancario.</p>}
        </section>
      ) : null}

      {importResult ? (
        <p className="bank-import-result" role="status">
          Importación terminada: {importResult.accepted_rows} aceptados, {importResult.duplicate_rows} duplicados y {importResult.rejections.length} rechazados.
        </p>
      ) : null}
      {error ? <p className="operations-error" role="alert">{error}</p> : null}
      {loading ? <p className="operations-loading">Cargando movimientos…</p> : null}

      {!loading && !accounts.length ? (
        <div className="operations-empty">
          <h3>Crea el primer alias de cuenta.</h3>
          <p>No ingreses números completos de cuentas; basta un nombre operativo y su moneda.</p>
        </div>
      ) : null}
      {!loading && accounts.length > 0 && !transactions.length ? (
        <div className="operations-empty">
          <h3>No hay movimientos importados.</h3>
          <p>El CSV debe incluir fecha y valor firmado: positivo para entradas y negativo para salidas.</p>
        </div>
      ) : null}

      {transactions.length ? (
        <div className="bank-transaction-list">
          {transactions.map((transaction) => (
            <article key={transaction.id} className={`bank-transaction ${transaction.status}`}>
              <div className="bank-transaction-main">
                <div>
                  <time dateTime={transaction.transaction_date}>{formatDate(transaction.transaction_date)}</time>
                  <strong>{transaction.description || "Movimiento sin descripción"}</strong>
                  {transaction.reference ? <small>Referencia: {transaction.reference}</small> : null}
                </div>
                <b className={Number(transaction.amount) > 0 ? "inflow" : "outflow"}>
                  {formatMoney(transaction.amount, transaction.currency_code)}
                </b>
              </div>
              <div className="bank-transaction-review">
                <span className={`bank-status ${transaction.status}`}>{statusLabels[transaction.status]}</span>
                {transaction.status === "suggested" ? (
                  <small>
                    Pago exacto del {transaction.suggested_payment_date ? formatDate(transaction.suggested_payment_date) : "mismo período"}.
                  </small>
                ) : transaction.match_candidate_count > 1 ? (
                  <small>{transaction.match_candidate_count} pagos posibles; requiere revisión manual.</small>
                ) : transaction.status === "pending" ? <small>Sin coincidencia única.</small> : null}
                {canManage ? (
                  <div className="bank-actions">
                    {transaction.status === "suggested" ? (
                      <>
                        <button type="button" onClick={() => void handleReview(transaction, "confirm")}>Confirmar</button>
                        <button type="button" onClick={() => void handleReview(transaction, "dismiss")}>Descartar</button>
                      </>
                    ) : null}
                    {transaction.status !== "reconciled" && transaction.status !== "excluded" ? (
                      <button type="button" onClick={() => void handleReview(transaction, "exclude")}>Excluir</button>
                    ) : null}
                    {(["reconciled", "dismissed", "excluded"] as BankTransactionStatus[]).includes(transaction.status) ? (
                      <button type="button" onClick={() => void handleReview(transaction, "reopen")}>Reabrir</button>
                    ) : null}
                  </div>
                ) : null}
              </div>
            </article>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function BankAccountForm({ token, companyId, onCreated }: {
  token: string;
  companyId: string;
  onCreated: (account: BankAccount) => Promise<void>;
}) {
  const [name, setName] = useState("");
  const [bankName, setBankName] = useState("");
  const [currency, setCurrency] = useState("COP");
  const [confirmed, setConfirmed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!confirmed) return;
    setSaving(true);
    setError(null);
    try {
      const account = await createBankAccount(token, companyId, {
        name: name.trim(),
        bank_name: bankName.trim() || null,
        currency_code: currency.trim().toUpperCase(),
        confirmed: true,
      });
      setName("");
      setBankName("");
      setConfirmed(false);
      await onCreated(account);
    } catch (cause) {
      setError(messageFor(cause, "No fue posible crear el alias de cuenta."));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="operations-form bank-account-form" onSubmit={submit}>
      <h3>Nuevo alias de cuenta</h3>
      <p>No guardamos el número completo de la cuenta.</p>
      <label>Alias<input value={name} onChange={(event) => setName(event.target.value)} maxLength={100} required placeholder="Ej. Cuenta operativa COP" /></label>
      <label>Banco (opcional)<input value={bankName} onChange={(event) => setBankName(event.target.value)} maxLength={100} /></label>
      <label>Moneda<input value={currency} onChange={(event) => setCurrency(event.target.value)} minLength={3} maxLength={3} pattern="[A-Za-z]{3}" required /></label>
      <label className="check-line confirm-line">
        <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />
        Confirmo la creación de este alias bancario.
      </label>
      {error ? <p className="form-error" role="alert">{error}</p> : null}
      <button className="secondary-action" disabled={!confirmed || saving}>{saving ? "Creando…" : "Crear alias"}</button>
    </form>
  );
}

function BankImportForm({ token, companyId, accounts, selectedAccountId, onAccountChange, onImported }: {
  token: string;
  companyId: string;
  accounts: BankAccount[];
  selectedAccountId: string;
  onAccountChange: (id: string) => void;
  onImported: (result: BankImportResult) => Promise<void>;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file || !selectedAccountId) return;
    setUploading(true);
    setError(null);
    try {
      const result = await importBankStatement(token, companyId, selectedAccountId, file);
      setFile(null);
      await onImported(result);
    } catch (cause) {
      setError(messageFor(cause, "No fue posible importar el extracto."));
    } finally {
      setUploading(false);
    }
  }

  return (
    <form className="operations-form bank-import-form" onSubmit={submit}>
      <h3>Importar extracto CSV</h3>
      <p>Columnas: fecha, valor, descripción, referencia y moneda. Sólo fecha y valor son obligatorias.</p>
      <label>Cuenta<select value={selectedAccountId} onChange={(event) => onAccountChange(event.target.value)} required>
        <option value="">Selecciona una cuenta</option>
        {accounts.filter((account) => account.status === "active").map((account) => <option key={account.id} value={account.id}>{account.name} · {account.currency_code}</option>)}
      </select></label>
      <label>Archivo<input type="file" accept=".csv,text/csv" onChange={(event) => setFile(event.target.files?.[0] || null)} required /></label>
      <p className="note-warning"><b>Revisa el archivo.</b> Evita incluir números completos de cuenta, documentos o datos de contacto en descripción y referencia.</p>
      {error ? <p className="form-error" role="alert">{error}</p> : null}
      <button className="secondary-action" disabled={!file || !selectedAccountId || uploading}>{uploading ? "Importando…" : "Importar extracto"}</button>
    </form>
  );
}

function BankBalanceSnapshotForm({ token, companyId, accounts, selectedAccountId, onAccountChange, onRecorded }: {
  token: string;
  companyId: string;
  accounts: BankAccount[];
  selectedAccountId: string;
  onAccountChange: (id: string) => void;
  onRecorded: () => Promise<void>;
}) {
  const [asOfDate, setAsOfDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [balance, setBalance] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedAccountId || !confirmed) return;
    setSaving(true);
    setError(null);
    try {
      await createBankBalanceSnapshot(token, companyId, selectedAccountId, {
        as_of_date: asOfDate,
        balance,
        confirmed: true,
      });
      setBalance("");
      setConfirmed(false);
      await onRecorded();
    } catch (cause) {
      setError(messageFor(cause, "No fue posible registrar el corte bancario."));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="operations-form bank-balance-form" onSubmit={submit}>
      <h3>Registrar saldo verificado</h3>
      <p>Ingresa el saldo que confirmaste para la fecha de corte. Puede ser negativo si existe sobregiro.</p>
      <label>Cuenta<select value={selectedAccountId} onChange={(event) => onAccountChange(event.target.value)} required>
        <option value="">Selecciona una cuenta</option>
        {accounts.filter((account) => account.status === "active").map((account) => <option key={account.id} value={account.id}>{account.name} · {account.currency_code}</option>)}
      </select></label>
      <label>Fecha de corte<input type="date" value={asOfDate} max={new Date().toISOString().slice(0, 10)} onChange={(event) => setAsOfDate(event.target.value)} required /></label>
      <label>Saldo verificado<input type="number" value={balance} onChange={(event) => setBalance(event.target.value)} step="0.01" required /></label>
      <label className="check-line confirm-line">
        <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />
        Confirmo que este es el saldo verificado de la cuenta en la fecha indicada.
      </label>
      {error ? <p className="form-error" role="alert">{error}</p> : null}
      <button className="secondary-action" disabled={!selectedAccountId || !balance || !confirmed || saving}>{saving ? "Registrando…" : "Registrar corte"}</button>
    </form>
  );
}

function formatMoney(amount: string, currency: string) {
  return new Intl.NumberFormat("es-CO", { style: "currency", currency, maximumFractionDigits: 2 }).format(Number(amount));
}

function formatDate(value: string) {
  const parsed = new Date(`${value.slice(0, 10)}T00:00:00Z`);
  return Number.isNaN(parsed.valueOf()) ? value : new Intl.DateTimeFormat("es-CO", { dateStyle: "medium", timeZone: "UTC" }).format(parsed);
}

function messageFor(cause: unknown, fallback: string) {
  return cause instanceof ApiError || cause instanceof Error ? cause.message : fallback;
}
