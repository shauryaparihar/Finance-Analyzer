import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/** The application code (everything except the generated UI kit in components/ui) must not use the `any` type. */
function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (path.endsWith(join("components", "ui"))) return [];
    if (statSync(path).isDirectory()) return sourceFiles(path);
    return /\.(ts|tsx)$/.test(name) && !name.endsWith(".test.ts") ? [path] : [];
  });
}

const ANY_TYPE = /(:\s*any\b|<any>|\bas any\b|\bany\[\]|Array<any>|Record<string,\s*any>)/;

describe("type safety", () => {
  it("has no `any` types in the application code", () => {
    const offenders = sourceFiles("src/app").flatMap((file) =>
      readFileSync(file, "utf8")
        .split("\n")
        .map((line, index) => ({ file, line: index + 1, text: line.trim() }))
        .filter(({ text }) => ANY_TYPE.test(text) && !text.startsWith("//") && !text.startsWith("*")),
    );
    expect(offenders).toEqual([]);
  });

  it("really does look at the source files", () => {
    expect(sourceFiles("src/app").length).toBeGreaterThan(15);
  });
});
