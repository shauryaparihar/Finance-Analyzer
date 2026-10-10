import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

/** The login credentials must stay out of browser storage, which any script on the page can read. */
describe("where login credentials live", () => {
  for (const file of ["src/app/api.ts", "src/app/context/AuthContext.tsx"]) {
    it(`${file} does not touch sessionStorage or localStorage`, () => {
      const source = readFileSync(file, "utf8").replace(/\/\/.*$/gm, "").replace(/\/\*[\s\S]*?\*\//g, "");
      expect(source).not.toMatch(/sessionStorage|localStorage|document\.cookie/);
    });
  }

  it("only the non-secret 'which analysis is open' choice may use storage, and not under a token-like name", () => {
    const source = readFileSync("src/app/context/AppContext.tsx", "utf8");
    expect(source).toContain('const KEY = "finsight.uploadId"');
    expect(source).not.toMatch(/token/i);
  });
});
