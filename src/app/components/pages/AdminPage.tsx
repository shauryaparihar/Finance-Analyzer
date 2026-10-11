import { useState } from "react";
import { Navigate } from "react-router";
import { getAdminOverview, listAdminUsers, listAudit, setUserActive, friendlyMessage } from "../../api";
import { useAuth } from "../../context/AuthContext";
import { useResource } from "../../hooks/useResource";
import { dateTime } from "../../lib/format";
import type { AdminUser } from "../../types";
import { Card, ErrorNotice, Notice, PageHeader, Pill, SectionTitle, Spinner } from "../common";
import { Button } from "../ui/button";

const label = (counts: Record<string, number>) =>
  Object.entries(counts).map(([name, n]) => `${name}: ${n}`).join(" · ") || "none";

/** Administrator view: how many accounts and analyses exist, and the ability to disable an account. */
export function AdminPage() {
  const { user } = useAuth();
  const overview = useResource(() => getAdminOverview(), []);
  const users = useResource(() => listAdminUsers(), []);
  const audit = useResource(() => listAudit(), []);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  if (user?.role !== "admin") return <Navigate to="/" replace />;

  async function toggle(account: AdminUser) {
    setBusyId(account.id);
    setActionError(null);
    try {
      await setUserActive(account.id, !account.is_active);
      users.reload();
      overview.reload();
      audit.reload();
    } catch (e) {
      setActionError(friendlyMessage(e));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="mx-auto max-w-5xl space-y-8 p-4 sm:p-8">
      <PageHeader title="Administration" subtitle="Accounts and service activity. Counts only: administrators cannot open anyone's transactions or results." />

      {overview.error !== null ? <ErrorNotice error={overview.error} onRetry={overview.reload} /> : !overview.data ? <Spinner label="Loading..." /> : (
        <Card>
          <SectionTitle>Overview</SectionTitle>
          <dl className="grid gap-4 text-sm sm:grid-cols-2">
            <div><dt className="text-muted-foreground">Accounts</dt><dd className="font-mono text-foreground">{overview.data.users_total} ({overview.data.users_active} active)</dd></div>
            <div><dt className="text-muted-foreground">Account types</dt><dd className="font-mono text-foreground">{label(overview.data.users_by_role)}</dd></div>
            <div><dt className="text-muted-foreground">Analyses stored</dt><dd className="font-mono text-foreground">{overview.data.uploads_total}</dd></div>
            <div><dt className="text-muted-foreground">Analyses by status</dt><dd className="font-mono text-foreground">{label(overview.data.uploads_by_status)}</dd></div>
            <div><dt className="text-muted-foreground">Uploaded in the last 7 days</dt><dd className="font-mono text-foreground">{overview.data.uploads_last_7_days}</dd></div>
          </dl>
        </Card>
      )}

      {actionError && <Notice tone="warn">{actionError}</Notice>}
      {users.error !== null ? <ErrorNotice error={users.error} onRetry={users.reload} /> : !users.data ? <Spinner label="Loading accounts..." /> : (
        <Card>
          <SectionTitle>Accounts</SectionTitle>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs uppercase text-muted-foreground">
                <tr><th className="py-2">Email</th><th>Type</th><th>Sign-in</th><th>Analyses</th><th>Created</th><th>Account</th><th>Signed in</th><th>Last active</th><th /></tr>
              </thead>
              <tbody>
                {users.data.map((account) => (
                  <tr key={account.id} className="border-t border-border">
                    <td className="max-w-[16rem] truncate py-3 text-foreground" title={account.email}>{account.email}</td>
                    <td><Pill tone="neutral">{account.role}</Pill></td>
                    <td className="whitespace-nowrap text-muted-foreground" title="How this account can be opened. Google means the address was proven by Google; Password means it was typed in and not checked.">{{ password: "Password", google: "Google", "google+password": "Google + password" }[account.sign_in_method]}</td>
                    <td className="font-mono">{account.upload_count}</td>
                    <td className="whitespace-nowrap text-muted-foreground">{dateTime(account.created_at)}</td>
                    <td title="Whether this account is allowed to sign in. Disabled accounts cannot."><Pill tone={account.is_active ? "good" : "bad"}>{account.is_active ? "Enabled" : "Disabled"}</Pill></td>
                    <td title="Whether the person has a live login session right now."><Pill tone={account.signed_in ? "info" : "neutral"}>{account.signed_in ? "Signed in" : "Signed out"}</Pill></td>
                    <td className="whitespace-nowrap text-muted-foreground">{account.last_active ? dateTime(account.last_active) : "never"}</td>
                    <td className="text-right">
                      {account.role !== "admin" && (
                        <Button variant="outline" size="sm" disabled={busyId === account.id} onClick={() => void toggle(account)}>
                          {account.is_active ? "Disable" : "Enable"}
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {audit.error !== null ? <ErrorNotice error={audit.error} onRetry={audit.reload} /> : !audit.data ? null : (
        <Card>
          <SectionTitle>Administrator activity</SectionTitle>
          {audit.data.length === 0 ? <p className="text-sm text-muted-foreground">No changes have been made yet.</p> : (
            <ul className="divide-y divide-border text-sm">
              {audit.data.map((entry) => (
                <li key={entry.id} className="flex flex-wrap items-baseline justify-between gap-2 py-2">
                  <span className="text-foreground">
                    {entry.admin_email} <span className="text-muted-foreground">{entry.action === "account_disabled" ? "disabled" : entry.action === "account_enabled" ? "enabled" : entry.action}</span> {entry.target_email}
                  </span>
                  <span className="whitespace-nowrap font-mono text-xs text-muted-foreground">{dateTime(entry.created_at)}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}
    </div>
  );
}
