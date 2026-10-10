import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/** Claims the product must not make unless the backend can back them up. */
function pageFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (path.endsWith(join("components", "ui"))) return [];
    if (statSync(path).isDirectory()) return pageFiles(path);
    return /\.tsx$/.test(name) && !name.endsWith(".test.tsx") ? [path] : [];
  });
}

const text = pageFiles("src/app").map((f) => readFileSync(f, "utf8")).join("\n").toLowerCase();

describe("what the screens are allowed to say", () => {
  it.each(["confidence interval", "ai recommendation", "ai-powered", "financial advisor", "guaranteed"])("never mentions %s", (phrase) => {
    expect(text).not.toContain(phrase);
  });

  it("never calls the app production-ready", () => {
    expect(text).not.toMatch(/production[- ]ready/);
  });

  it("only mentions fraud to say the feature is NOT fraud detection", () => {
    const mentions = text.match(/[^.\n]*fraud[^.\n]*/g) ?? [];
    expect(mentions.length).toBeGreaterThan(0);
    for (const sentence of mentions) {
      expect(sentence).toMatch(/not (mean )?fraud|not a fraud|fraud check/);
    }
  });
});
