import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));

test("badge.tsx exists", () => {
  const path = resolve(__dirname, "../components/ui/badge.tsx");
  assert.ok(existsSync(path), "components/ui/badge.tsx must exist");
});

test("badge.tsx exports Badge and BadgeVariant (source check)", () => {
  const src = readFileSync(
    resolve(__dirname, "../components/ui/badge.tsx"),
    "utf8"
  );
  assert.ok(src.includes("export function Badge"), "must export Badge");
  assert.ok(src.includes("export type BadgeVariant"), "must export BadgeVariant type");
  assert.ok(src.includes("export interface BadgeProps"), "must export BadgeProps");
  assert.ok(src.includes("badgeVariants"), "must define badgeVariants via cva");
});
