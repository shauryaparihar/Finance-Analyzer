import { describe, expect, it } from "vitest";
import { amount, dateTime, duration, monthLabel, percent, shortDate } from "./format";
import { categoryOptions, categorySource, checkReason, confidenceCell, confidenceLabel, LOW_CONFIDENCE, reviewedCount, shownStatus, usesModelGuess, withoutDecision } from "./review";
import { ActivityClock, IDLE_LOGOUT_MS, IDLE_NOTICE, isIdle } from "./idle";
import { hasResults, isActive, moduleRun, whyNoResult } from "./status";
import type { ModuleStatus } from "../types";

const row = (over: Partial<Parameters<typeof checkReason>[0]> = {}) => ({
  category: "Groceries", predicted_category: "Groceries", source_category: null, review_required: false, prediction_confidence: 0.95, confirmed_category: null, ...over,
});

describe("formatting", () => {
  it("formats amounts without assuming a currency", () => {
    expect(amount(1234.5)).toBe("1,234.50");
    expect(amount(-2000)).toBe("-2,000.00");
    expect(amount(0)).toBe("0.00");
  });
  it("formats percentages, dates and durations", () => {
    expect(percent(27.123)).toBe("27.1%");
    expect(percent(-3.04, 0)).toBe("-3%");
    expect(shortDate("2025-03-05")).toBe("05 Mar 2025");
    expect(shortDate(null)).toBe("-");
    expect(shortDate("garbage")).toBe("garbage");
    expect(dateTime(null)).toBe("-");
    expect(duration(450)).toBe("450 ms");
    expect(duration(4031)).toBe("4.0 s");
    expect(duration(null)).toBe("-");
    expect(monthLabel("2026-04")).toBe("April 2026");
    expect(monthLabel(null)).toBe("-");
    expect(monthLabel("not-a-month")).toBe("not-a-month");
  });
});

describe("which rows to check", () => {
  it("flags uncategorized rows and unsure guesses, and leaves confident or decided rows alone", () => {
    expect(checkReason(row())).toBeNull();
    expect(checkReason(row({ category: "Uncategorized", prediction_confidence: 0 }))).toBe("No category yet");
    expect(checkReason(row({ review_required: true }))).toBe("No category yet");
    expect(checkReason(row({ prediction_confidence: LOW_CONFIDENCE - 0.01 }))).toBe("Model is unsure");
    expect(checkReason(row({ prediction_confidence: LOW_CONFIDENCE }))).toBeNull(); // exactly at the limit is fine
    expect(checkReason(row({ prediction_confidence: null }))).toBeNull(); // the user's own label has no model confidence
  });
  it("stops flagging a row once the person has chosen its category", () => {
    expect(checkReason(row({ category: "Uncategorized", confirmed_category: "Rent" }))).toBeNull();
    expect(checkReason(row({ prediction_confidence: 0.2, confirmed_category: "Rent" }))).toBeNull();
  });
  it("credits the file, not the model, when the file already had that category", () => {
    const sameAsModel = row({ source_category: "Groceries" }); // the file said Groceries and the model agreed
    expect(categorySource(sameAsModel)).toBe("file");
    expect(usesModelGuess(sameAsModel)).toBe(false);
    expect(checkReason(row({ source_category: "Groceries", prediction_confidence: 0.2 }))).toBeNull(); // model doubt is irrelevant
    expect(categorySource(row())).toBe("model");
    expect(categorySource(row({ confirmed_category: "Rent", source_category: "Groceries" }))).toBe("yours");
    expect(categorySource(row({ category: "Uncategorized", predicted_category: "Uncategorized" }))).toBe("none");
  });
  it("only blames the model when its guess is the category being used", () => {
    // the person's own file said "Mine"; the model's low-confidence guess for that row is irrelevant
    expect(checkReason(row({ category: "Mine", source_category: "Mine", predicted_category: "Shopping", prediction_confidence: 0.3 }))).toBeNull();
    expect(usesModelGuess(row())).toBe(true);
    expect(usesModelGuess(row({ category: "Mine", source_category: "Mine", predicted_category: "Shopping" }))).toBe(false);
    expect(usesModelGuess(row({ confirmed_category: "Rent" }))).toBe(false);
  });
  it("shows confidence as a whole-number percentage", () => {
    expect(confidenceLabel(0.934)).toBe("93%");
    expect(confidenceLabel(null)).toBe("No guess");
  });
  it("offers the model's categories plus the user's own, sorted, without duplicates or Uncategorized", () => {
    expect(categoryOptions(["Rent", "Groceries"], ["Groceries", "My Label", "Uncategorized"])).toEqual(["Groceries", "My Label", "Rent"]);
  });
});

describe("upload status", () => {
  it("knows which statuses keep polling and which have results", () => {
    expect(["queued", "processing"].every((s) => isActive(s as never))).toBe(true);
    expect(["completed", "partial", "failed"].some((s) => isActive(s as never))).toBe(false);
    expect(hasResults("completed") && hasResults("partial")).toBe(true);
    expect(hasResults("failed") || hasResults("queued") || hasResults("processing")).toBe(false);
  });
  const modules = (status: ModuleStatus["status"], message: string | null): ModuleStatus[] => [
    { module: "forecast", status, duration_ms: null, model_version: null, error_code: null, error_message: message, started_at: null, finished_at: null },
  ];
  it("explains a missing result from what the backend recorded", () => {
    expect(whyNoResult(modules("failed", "Forecast failed."), "forecast")).toBe("Forecast failed.");
    expect(whyNoResult(modules("skipped", "Need 90 days."), "forecast")).toBe("Need 90 days.");
    expect(whyNoResult(modules("running", null), "forecast")).toBe("This step has not finished yet.");
    expect(whyNoResult([], "anomaly")).toBe("No result is available for this upload.");
    expect(moduleRun(modules("completed", null), "forecast")?.status).toBe("completed");
  });
});

describe("the model confidence column", () => {
  it("shows the model's confidence only when its guess is the category shown", () => {
    expect(confidenceCell(row({ prediction_confidence: 0.82 }))).toBe("82%");
  });
  it("says there was no guess when the model made none (blank or unrecognised text)", () => {
    expect(confidenceCell(row({ category: "Groceries", confirmed_category: "Groceries", predicted_category: null, prediction_confidence: null }))).toBe("No guess");
    expect(confidenceCell(row({ category: "Uncategorized", predicted_category: "Uncategorized", prediction_confidence: null }))).toBe("No guess");
    // the model still scores such a row, but declined to name a category: that is "no guess", not "not used"
    expect(confidenceCell(row({ category: "Uncategorized", predicted_category: "Uncategorized", prediction_confidence: 0.31, review_required: true }))).toBe("No guess");
  });
  it("says the guess was not used when the person's choice or their file's category is shown instead", () => {
    expect(confidenceCell(row({ category: "Fixed", confirmed_category: "Fixed", predicted_category: "Groceries", prediction_confidence: 0.9 }))).toBe("Not used");
  });
});

describe("unusual-transaction decisions shown before the server answers", () => {
  const items = [
    { transaction_id: 1, review_status: "unreviewed" as const },
    { transaction_id: 2, review_status: "confirmed" as const },
  ];

  it("shows a decision still being saved instead of the server's last answer", () => {
    expect(shownStatus(items[0], {})).toBe("unreviewed");
    expect(shownStatus(items[0], { 1: "dismissed" })).toBe("dismissed");
    expect(shownStatus(items[1], { 2: "unreviewed" })).toBe("unreviewed"); // Undo shows at once too
  });

  it("counts reviewed items using the decisions being saved", () => {
    expect(reviewedCount(items, {})).toBe(1);
    expect(reviewedCount(items, { 1: "confirmed" })).toBe(2);
    expect(reviewedCount(items, { 2: "unreviewed" })).toBe(0);
  });

  it("goes back to the server's answer when a save fails, without touching other decisions", () => {
    const saving = { 1: "confirmed" as const, 2: "unreviewed" as const };
    const after = withoutDecision(saving, 1);
    expect(after).toEqual({ 2: "unreviewed" });
    expect(saving).toEqual({ 1: "confirmed", 2: "unreviewed" }); // original not modified
    expect(shownStatus(items[0], after)).toBe("unreviewed");
  });
});

describe("logging out after inactivity", () => {
  const MIN = 60 * 1000;
  it("is idle exactly when the limit has passed", () => {
    expect(isIdle(0, 14 * MIN + 59_000)).toBe(false);
    expect(isIdle(0, 15 * MIN)).toBe(true);
    expect(isIdle(1000, 16 * MIN)).toBe(true);
  });
  it("uses 15 minutes, the lifetime of an access token", () => {
    expect(IDLE_LOGOUT_MS).toBe(15 * MIN);
    expect(IDLE_NOTICE).toContain("15 minutes");
  });
  it("activity moves the clock forward, and news from another tab never moves it backward", () => {
    const clock = new ActivityClock(0);
    expect(clock.idle(15 * MIN)).toBe(true);
    clock.touch(10 * MIN);
    expect(clock.idle(15 * MIN)).toBe(false);
    clock.touch(5 * MIN); // an older message arriving late
    expect(clock.lastActivity).toBe(10 * MIN);
    expect(clock.idle(25 * MIN)).toBe(true);
  });
});
