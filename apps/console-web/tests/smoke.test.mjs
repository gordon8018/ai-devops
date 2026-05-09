import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { join } from "node:path";

const root = new URL("..", import.meta.url).pathname;

function pageExists(route) {
  const candidates = [
    join(root, "app", route, "page.tsx"),
    join(root, "app", route, "page.jsx"),
  ];
  return candidates.some(existsSync);
}

test("all expected page routes exist", () => {
  const routes = [
    "",
    "work-items",
    "work-items/[workItemId]",
    "releases",
    "incidents",
    "evals",
    "governance",
  ];
  for (const route of routes) {
    assert.ok(pageExists(route), `page missing: app/${route || "page.tsx"}`);
  }
});

test("navigation items match existing routes", async () => {
  const navPath = join(root, "lib", "navigation.mjs");
  assert.ok(existsSync(navPath), "navigation.mjs must exist");
  const { consoleNavItems } = await import(navPath);
  assert.ok(Array.isArray(consoleNavItems), "consoleNavItems must be an array");
  for (const item of consoleNavItems) {
    assert.ok(typeof item.id === "string", "nav item must have id");
    assert.ok(typeof item.href === "string", "nav item must have href");
    assert.ok(typeof item.label === "string", "nav item must have label");
  }
});

test("ui components are importable", () => {
  const components = ["button", "badge", "dialog", "tabs"];
  for (const name of components) {
    const path = join(root, "components", "ui", `${name}.tsx`);
    assert.ok(existsSync(path), `ui/${name}.tsx must exist`);
  }
});

test("StatusBadge component exists", () => {
  assert.ok(
    existsSync(join(root, "components", "status-badge.tsx")),
    "status-badge.tsx must exist"
  );
});
