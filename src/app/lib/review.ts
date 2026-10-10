import type { TransactionRow } from "../types";

/** Below this the model's guess is flagged for a second look. It is a ranking signal, not a probability of being right. */
export const LOW_CONFIDENCE = 0.7;

export const UNCATEGORIZED = "Uncategorized";

type Reviewable = Pick<
  TransactionRow,
  "category" | "review_required" | "prediction_confidence" | "confirmed_category" | "predicted_category" | "source_category"
>;

export type CategorySource = "yours" | "file" | "model" | "none";

/** Where the category shown came from: the person's own choice, their uploaded file, the model, or nowhere yet. */
export function categorySource(row: Reviewable): CategorySource {
  if (row.confirmed_category) return "yours";
  if (row.source_category) return "file";
  if (row.predicted_category !== null && row.predicted_category === row.category && row.category !== UNCATEGORIZED) return "model";
  return "none";
}

/** True only when the category shown is the model's own guess. A label in the file wins even if the model agrees. */
export function usesModelGuess(row: Reviewable): boolean {
  return categorySource(row) === "model";
}

/** Why a row should be checked, or null if it needs no attention. */
export function checkReason(row: Reviewable): string | null {
  if (row.confirmed_category) return null; // the person already decided
  if (row.review_required || row.category === UNCATEGORIZED) return "No category yet";
  if (usesModelGuess(row) && row.prediction_confidence !== null && row.prediction_confidence < LOW_CONFIDENCE) return "Model is unsure";
  return null;
}

export function confidenceLabel(confidence: number | null): string {
  return confidence === null ? "No guess" : `${Math.round(confidence * 100)}%`;
}

/** What the confidence column says: the model's confidence when its guess is what is shown, otherwise why there is none. */
export function confidenceCell(row: Reviewable): string {
  if (usesModelGuess(row)) return confidenceLabel(row.prediction_confidence);
  return row.prediction_confidence === null ? "No guess" : "Not used";
}

/** Category choices for a dropdown: the model's categories plus any the user already has, without duplicates. */
export function categoryOptions(modelCategories: string[], seen: string[]): string[] {
  return Array.from(new Set([...modelCategories, ...seen])).filter((c) => c !== UNCATEGORIZED).sort((a, b) => a.localeCompare(b));
}

type ReviewStatus = "unreviewed" | "confirmed" | "dismissed";
type ReviewItem = { transaction_id: number; review_status: ReviewStatus };

/** Status to show: a decision still being saved wins over what the server last sent. */
export function shownStatus(item: ReviewItem, saving: Record<number, ReviewStatus>): ReviewStatus {
  return saving[item.transaction_id] ?? item.review_status;
}

export function reviewedCount(items: ReviewItem[], saving: Record<number, ReviewStatus>): number {
  return items.filter((item) => shownStatus(item, saving) !== "unreviewed").length;
}

/** The decisions still being saved, minus one that failed (so the screen goes back to what the server has). */
export function withoutDecision(saving: Record<number, ReviewStatus>, transactionId: number): Record<number, ReviewStatus> {
  const rest = { ...saving };
  delete rest[transactionId];
  return rest;
}
