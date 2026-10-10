import { DragEvent, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { FileText, Loader2, Trash2, Upload } from "lucide-react";
import { deleteUpload, listUploads, uploadFile } from "../../api";
import { useAppContext } from "../../context/AppContext";
import { useAuth } from "../../context/AuthContext";
import { useResource } from "../../hooks/useResource";
import { dateTime } from "../../lib/format";
import { UPLOAD_STATUS_LABELS, isActive } from "../../lib/status";
import type { AmountConvention, UploadAccepted, UploadItem, UploadStatus } from "../../types";
import { Card, ErrorNotice, Notice, PageHeader, Pill, SectionTitle, Tone } from "../common";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter,
  AlertDialogHeader, AlertDialogTitle,
} from "../ui/alert-dialog";
import { Button } from "../ui/button";

const CONVENTIONS: { value: AmountConvention; label: string }[] = [
  { value: "auto", label: "Detect automatically (recommended)" },
  { value: "expenses_positive", label: "Spending is positive; income and refunds are negative" },
  { value: "expenses_negative", label: "Spending is negative (bank-statement style)" },
];

const STATUS_TONE: Record<UploadStatus, Tone> = { queued: "info", processing: "info", completed: "good", partial: "warn", failed: "bad" };

export function UploadPage() {
  const navigate = useNavigate();
  const { uploadId, setUploadId } = useAppContext();
  const readOnly = useAuth().user?.role === "demo";
  const fileInput = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [convention, setConvention] = useState<AmountConvention>("auto");
  const [error, setError] = useState<unknown>(null);
  const [result, setResult] = useState<UploadAccepted | null>(null);
  const [toDelete, setToDelete] = useState<UploadItem | null>(null);
  const [deleteError, setDeleteError] = useState<unknown>(null);

  const history = useResource(listUploads, []);
  const anyActive = history.data?.some((u) => isActive(u.status)) ?? false;
  // The guest has exactly one analysis (the sample), so open it for them instead of asking them to find the Open button.
  useEffect(() => {
    if (readOnly && !uploadId && history.data && history.data.length > 0) setUploadId(history.data[0].id);
  }, [readOnly, uploadId, history.data, setUploadId]);
  useEffect(() => {
    if (!anyActive) return;
    const timer = setTimeout(history.reload, 3000); // keep the list fresh while something is running
    return () => clearTimeout(timer);
  }, [anyActive, history.data, history.reload]);

  async function handleFile(file: File) {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const accepted = await uploadFile(file, convention);
      setUploadId(accepted.upload_id);
      history.reload();
      if (accepted.reused || accepted.rows_dropped > 0) setResult(accepted);
      else navigate("/overview");
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) void handleFile(file);
  }

  async function confirmDelete() {
    if (!toDelete) return;
    try {
      await deleteUpload(toDelete.id);
      if (toDelete.id === uploadId) setUploadId(null);
      setToDelete(null);
      setDeleteError(null);
      history.reload();
    } catch (e) {
      setDeleteError(e);
    }
  }

  return (
    <div className="mx-auto max-w-4xl space-y-8 p-4 sm:p-8">
      <PageHeader title="Upload transactions" subtitle="Import a CSV export of your transactions to see spending, budget risk and anything unusual." />

      {readOnly ? (
        <Notice tone="info">The demo account is read-only, so uploading is switched off. Open the sample analysis below, or log out and create your own account to upload a file.</Notice>
      ) : (
      <Card>
        <div
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={(e) => { e.preventDefault(); setDragging(false); }}
          onDrop={onDrop}
          className={`rounded-lg border-2 border-dashed p-6 text-center transition-all sm:p-10 ${dragging ? "border-primary bg-primary/10" : "border-border hover:border-primary/50"}`}
        >
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-secondary">
            <Upload className="h-7 w-7 text-primary" />
          </div>
          <h3 className="mb-1 font-sans text-lg text-foreground">Drop your CSV file here</h3>
          <p className="mb-4 text-sm text-muted-foreground">or choose a file (up to 5 MB and 50,000 rows)</p>
          <input
            ref={fileInput} type="file" accept=".csv" className="hidden" id="file-upload" disabled={busy}
            onChange={(e) => { const file = e.target.files?.[0]; if (file) void handleFile(file); }}
          />
          <Button onClick={() => fileInput.current?.click()} disabled={busy} className="px-6">
            {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <FileText className="mr-2 h-4 w-4" />}
            {busy ? "Uploading..." : "Choose file"}
          </Button>
        </div>

        <div className="mt-6">
          <label htmlFor="convention" className="mb-1 block text-sm text-muted-foreground">How does your file write amounts?</label>
          <select
            id="convention" value={convention} onChange={(e) => setConvention(e.target.value as AmountConvention)}
            className="w-full rounded-md border border-border bg-input px-3 py-2 text-sm text-foreground outline-none focus:border-primary"
          >
            {CONVENTIONS.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
          </select>
          <p className="mt-1 text-xs text-muted-foreground">
            If the file mixes both signs almost evenly, automatic detection will ask you to choose here instead of guessing.
          </p>
        </div>

        <div className="mt-4 space-y-3">
          {error !== null && <ErrorNotice error={error} />}
          {result && (
            <Notice tone={result.reused ? "info" : "warn"}>
              <p>{result.message}</p>
              {result.rows_dropped > 0 && (
                <p className="mt-1">{result.rows_dropped} of {result.rows_received} rows were skipped because their date or amount could not be read.</p>
              )}
              <button onClick={() => navigate("/overview")} className="mt-2 text-primary underline-offset-4 hover:underline">Open this analysis</button>
            </Notice>
          )}
        </div>
      </Card>
      )}

      <Card>
        <SectionTitle>Expected CSV columns</SectionTitle>
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full min-w-[480px] text-sm">
            <thead className="bg-secondary">
              <tr>{["Column", "Required", "Example"].map((h) => <th key={h} className="px-4 py-3 text-left font-mono text-xs uppercase tracking-wider text-muted-foreground">{h}</th>)}</tr>
            </thead>
            <tbody className="divide-y divide-border">
              {[
                ["date", true, "2025-03-15"],
                ["amount", true, "52.40"],
                ["description", false, "WHOLE FOODS MKT 10234"],
                ["category", false, "Groceries"],
              ].map(([name, required, example]) => (
                <tr key={String(name)}>
                  <td className="px-4 py-3 font-mono text-foreground">{String(name)}</td>
                  <td className="px-4 py-3"><Pill tone={required ? "good" : "neutral"}>{required ? "Yes" : "Optional"}</Pill></td>
                  <td className="px-4 py-3 font-mono text-muted-foreground">{String(example)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-xs text-muted-foreground">
          Without a description a transaction stays &quot;Uncategorized&quot; for you to categorize. A category column from your file is kept as you wrote it.
        </p>
        <p className="mt-2 text-xs text-muted-foreground">
          No file handy? The project&apos;s <span className="font-mono">data</span> folder has two practice files: <span className="font-mono">sample_transactions.csv</span> (categories already filled in) and{" "}
          <span className="font-mono">sample_descriptions_only.csv</span> (no categories, so the model categorizes it and the Category review screen has rows to check).
        </p>
      </Card>

      <Card>
        <SectionTitle>Your analyses</SectionTitle>
        {history.error !== null && <ErrorNotice error={history.error} onRetry={history.reload} />}
        {history.loading && !history.data && <p className="text-sm text-muted-foreground">Loading...</p>}
        {history.data?.length === 0 && <p className="text-sm text-muted-foreground">Nothing yet. Upload a file above to get started.</p>}
        {history.data && history.data.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] text-sm">
              <thead>
                <tr className="border-b border-border text-left font-mono text-xs uppercase tracking-wider text-muted-foreground">
                  <th className="py-2 pr-3">File</th><th className="py-2 pr-3">Uploaded</th><th className="py-2 pr-3 text-right">Rows</th><th className="py-2 pr-3">Status</th><th className="py-2 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {history.data.map((u) => (
                  <tr key={u.id} className={u.id === uploadId ? "bg-secondary/40" : ""}>
                    <td className="max-w-[14rem] truncate py-3 pr-3 text-foreground" title={u.filename}>{u.filename}</td>
                    <td className="whitespace-nowrap py-3 pr-3 text-muted-foreground">{dateTime(u.created_at)}</td>
                    <td className="py-3 pr-3 text-right font-mono">{u.row_count}</td>
                    <td className="py-3 pr-3">
                      <Pill tone={STATUS_TONE[u.status]}>
                        {isActive(u.status) && <Loader2 className="h-3 w-3 animate-spin" />}
                        {UPLOAD_STATUS_LABELS[u.status]}
                      </Pill>
                    </td>
                    <td className="whitespace-nowrap py-3 text-right">
                      <Button variant="outline" size="sm" onClick={() => { setUploadId(u.id); navigate("/overview"); }}>Open</Button>
                      {!readOnly && <Button variant="ghost" size="sm" aria-label={`Delete ${u.filename}`} onClick={() => { setDeleteError(null); setToDelete(u); }}>
                        <Trash2 className="h-4 w-4 text-destructive" />
                      </Button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {history.data?.some((u) => u.status === "failed" || u.status === "partial") && (
          <p className="mt-3 text-xs text-muted-foreground">To re-run a failed or partly completed analysis, delete it and upload the file again.</p>
        )}
      </Card>

      <AlertDialog open={toDelete !== null} onOpenChange={(open) => { if (!open) setToDelete(null); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this analysis?</AlertDialogTitle>
            <AlertDialogDescription>
              {toDelete?.filename} and everything stored for it (transactions, results, your category corrections and reviews) will be permanently deleted. This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          {deleteError !== null && <ErrorNotice error={deleteError} />}
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={(e) => { e.preventDefault(); void confirmDelete(); }} className="bg-destructive text-white hover:bg-destructive/90">Delete</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
