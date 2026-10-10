import type { ModuleName, ModuleStatus, RiskStatus, RunStatus, UploadStatus } from "../types";

/** Still being worked on: keep polling. */
export function isActive(status: UploadStatus): boolean {
  return status === "queued" || status === "processing";
}

/** Results can be shown (some modules may have failed when the status is partial). */
export function hasResults(status: UploadStatus): boolean {
  return status === "completed" || status === "partial";
}

export const MODULE_LABELS: Record<ModuleName, string> = {
  categorization: "Categorize transactions",
  forecast: "Spending forecast",
  anomaly: "Unusual transactions",
  summary: "Summary",
};

export const RUN_STATUS_LABELS: Record<RunStatus, string> = {
  pending: "Waiting",
  running: "Running",
  completed: "Done",
  failed: "Failed",
  skipped: "Skipped",
};

export const UPLOAD_STATUS_LABELS: Record<UploadStatus, string> = {
  queued: "Queued",
  processing: "Processing",
  completed: "Completed",
  partial: "Partly completed",
  failed: "Failed",
};

export const RISK_LABELS: Record<RiskStatus, string> = {
  on_track: "On track",
  near_limit: "Near limit",
  projected_over: "Projected over",
  over_budget: "Over budget",
};

export function moduleRun(modules: ModuleStatus[], name: ModuleName): ModuleStatus | undefined {
  return modules.find((m) => m.module === name);
}

/** A readable explanation for why a module has no result, taken from what the backend recorded. */
export function whyNoResult(modules: ModuleStatus[], name: ModuleName): string {
  const run = moduleRun(modules, name);
  if (run?.status === "failed") return run.error_message ?? "This step failed.";
  if (run?.status === "skipped") return run.error_message ?? "There was not enough data for this step.";
  if (run?.status === "pending" || run?.status === "running") return "This step has not finished yet.";
  return "No result is available for this upload.";
}
