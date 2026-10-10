import { ReactNode, useEffect } from "react";
import { ApiError } from "../api";
import { useAppContext } from "../context/AppContext";
import { useUploadStatus } from "../hooks/useUploadStatus";
import { MODULE_LABELS, hasResults, isActive } from "../lib/status";
import type { UploadStatusResponse } from "../types";
import { Card, EmptyState, ErrorNotice, Notice, Spinner } from "./common";
import { ModuleProgress } from "./ModuleProgress";

/**
 * Wraps every results page. It handles "no upload chosen", "still processing" (with per-step progress),
 * "failed" and "partly completed", and only renders the page once there are results to show.
 */
export function UploadGate({ children }: { children: (status: UploadStatusResponse) => ReactNode }) {
  const { uploadId, setUploadId } = useAppContext();
  const { status, error, loading, reload } = useUploadStatus(uploadId);

  const gone = error instanceof ApiError && error.status === 404;
  useEffect(() => {
    if (gone) setUploadId(null); // the analysis was deleted: forget the selection
  }, [gone, setUploadId]);

  if (!uploadId || gone) {
    return (
      <EmptyState title="No analysis selected" linkTo="/" linkLabel="Go to Upload">
        {gone ? "That analysis no longer exists. " : ""}Upload a CSV or open one of your earlier analyses to see this page.
      </EmptyState>
    );
  }
  if (loading && !status) return <Spinner label="Loading analysis status..." />;
  if (error) return <div className="p-6 sm:p-8"><ErrorNotice error={error} onRetry={reload} /></div>;
  if (!status) return null;

  if (isActive(status.status)) {
    return (
      <div className="mx-auto max-w-xl p-6 sm:p-8">
        <Card>
          <h2 className="mb-1 font-sans text-xl text-foreground">
            {status.status === "queued" ? "Waiting to start..." : "Analysing your transactions..."}
          </h2>
          <p className="mb-4 text-sm text-muted-foreground">This page updates by itself. It usually takes a few seconds.</p>
          <ModuleProgress modules={status.modules} />
        </Card>
      </div>
    );
  }

  if (!hasResults(status.status)) {
    return (
      <div className="mx-auto max-w-xl p-6 sm:p-8">
        <Card>
          <h2 className="mb-1 font-sans text-xl text-foreground">This analysis failed</h2>
          <p className="mb-4 text-sm text-muted-foreground">
            {status.error_summary ?? "Something went wrong while analysing the file."} You can delete it from the Upload page and try again.
          </p>
          <ModuleProgress modules={status.modules} />
        </Card>
      </div>
    );
  }

  const failed = status.modules.filter((m) => m.status === "failed");
  return (
    <>
      {status.status === "partial" && (
        <div className="px-4 pt-4 sm:px-8 sm:pt-6">
          <Notice tone="warn">
            Part of this analysis could not be completed ({failed.map((m) => MODULE_LABELS[m.module]).join(", ")}). The other results below are still valid.
          </Notice>
        </div>
      )}
      {children(status)}
    </>
  );
}
