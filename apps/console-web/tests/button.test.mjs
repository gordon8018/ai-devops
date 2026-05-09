import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));

test("button.tsx exists", () => {
  const path = resolve(__dirname, "../components/ui/button.tsx");
  assert.ok(existsSync(path), "components/ui/button.tsx must exist");
});

test("button.tsx exports Button (source check)", () => {
  const src = readFileSync(
    resolve(__dirname, "../components/ui/button.tsx"),
    "utf8"
  );
  assert.ok(src.includes("export const Button"), "must export Button");
  assert.ok(src.includes("export interface ButtonProps"), "must export ButtonProps");
  assert.ok(src.includes("buttonVariants"), "must define buttonVariants via cva");
});
