import type { TransactionRow } from "../types";

/** Below this the model's guess is flagged for a second look. It is a ranking signal, not a probability of being right. */
export const LOW_CONFIDENCE = 0.7;

export const UNCATEGORIZED = "Uncategorized";

type Reviewable = Pick<TransactionRow, "category" | "review_required" | "prediction_confidence" | "confirmed_category" | "predicted_category">;

/** True when the category shown is the model's own guess (not the person's choice or a label from their file). */
export function usesModelGuess(row: Reviewable): boolean {
  return !row.confirmed_category && row.predicted_category !== null && row.predicted_category === row.category;
}

/** Why a row should be checked, or null if it needs no attention. */
export function checkReason(row: Reviewable): string | null {
  if (row.confirmed_category) return null; // the person already decided
  if (row.review_required || row.category === UNCATEGORIZED) return "No category yet";
  if (usesModelGuess(row) && row.prediction_confidence !== null && row.prediction_confidence < LOW_CONFIDENCE) return "Model is unsure";
  return null;
}

export function confidenceLabel(confidence: number | null): string {
  return confidence === null ? "-" : `${Math.round(confidence * 100)}%`;
}

/** Category choices for a dropdown: the model's categories plus any the user already has, without duplicates. */
export function categoryOptions(modelCategories: string[], seen: string[]): string[] {
  return Array.from(new Set([...modelCategories, ...seen])).filter((c) => c !== UNCATEGORIZED).sort((a, b) => a.localeCompare(b));
}
