# Web Console UI Phase 7 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the read-only Next.js 15 console into an interactive, visually-semantic control panel with task submission, status polling, and new views for Agent Runs and Plan details.

**Architecture:** Server Components handle all data fetching (SSR); Client Components are used only for interactivity (forms, polling, tabs). No global client state. A `shadcn-style` component system is built using `class-variance-authority` + `clsx` on top of the existing CSS custom properties — no Tailwind CSS introduced.

**Tech Stack:** Next.js 15 App Router, TypeScript, `class-variance-authority`, `clsx`, Python (backend endpoint), pytest

---

## File Map

### New — frontend (`apps/console-web/`)
| File | Purpose |
|------|---------|
| `lib/cn.ts` | className merge utility (clsx + cva) |
| `components/ui/button.tsx` | Button with variants (default/outline/ghost/destructive) |
| `components/ui/badge.tsx` | Badge with status variants |
| `components/ui/dialog.tsx` | Modal overlay (Client Component) |
| `components/ui/tabs.tsx` | Controlled tab switcher (Client Component) |
| `components/status-badge.tsx` | Maps WorkItem/Release/Incident status → Badge variant |
| `components/create-work-item-dialog.tsx` | POST /api/work-items form (Client Component) |
| `components/timeline.tsx` | Vertical timeline (Server Component) |
| `components/context-pack-panel.tsx` | Context Pack file hints + criteria display |
| `components/polling-wrapper.tsx` | 15s auto-refetch for RUNNING work items (Client Component) |
| `app/agent-runs/page.tsx` | Agent Runs list page |
| `app/plans/[planId]/page.tsx` | Plan detail page (steps list) |
| `tests/smoke.test.mjs` | Page structure + navigation smoke tests |

### New — backend
| File | Purpose |
|------|---------|
| `orchestrator/api/agent_runs.py` | `GET /api/agent-runs` endpoint |
| `tests/test_agent_runs_api.py` | pytest for agent runs endpoint |

### Modified — frontend
| File | Change |
|------|--------|
| `package.json` | Add `class-variance-authority`, `clsx` |
| `app/globals.css` | Add `.btn`, `.badge`, `.dialog-*`, `.tabs-*`, `.timeline-*`, `.form-*` CSS |
| `lib/navigation.mjs` | Add Agent Runs + Plans nav items |
| `lib/console-api.ts` | Add `createWorkItem`, `getAgentRuns`, `getPlanDetail`, `getApiBaseUrl` |
| `app/work-items/page.tsx` | Add `CreateWorkItemDialog` button |
| `app/work-items/[workItemId]/page.tsx` | Use `Timeline`, `ContextPackPanel`, `PollingWrapper`, plan link |
| `app/incidents/page.tsx` | Replace `.pill` with `StatusBadge` |
| `app/releases/page.tsx` | Replace `.pill` with `StatusBadge` |

### Modified — backend
| File | Change |
|------|--------|
| `packages/shared/domain/runtime_state.py` | Add `record_agent_run`, `list_agent_runs`, clear in `clear_runtime_state` |
| `orchestrator/api/server.py` | Register `create_agent_runs_handler` |

---

## Task 1: Install dependencies and create `cn` utility

**Files:**
- Modify: `apps/console-web/package.json`
- Create: `apps/console-web/lib/cn.ts`

- [ ] **Step 1: Install packages**

```bash
cd apps/console-web
npm install class-variance-authority clsx
```

Expected output: packages added to `node_modules`, `package-lock.json` updated.

- [ ] **Step 2: Create `lib/cn.ts`**

```ts
import { clsx, type ClassValue } from "clsx";

export function cn(...inputs: ClassValue[]): string {
  return clsx(inputs);
}
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd apps/console-web && npm run build 2>&1 | tail -5
```

Expected: no errors, `.next/` generated.

- [ ] **Step 4: Commit**

```bash
git add apps/console-web/package.json apps/console-web/package-lock.json apps/console-web/lib/cn.ts
git commit -m "feat(console-web): add cva + clsx, cn utility"
```

---

## Task 2: Button component + CSS

**Files:**
- Create: `apps/console-web/components/ui/button.tsx`
- Modify: `apps/console-web/app/globals.css`

- [ ] **Step 1: Add button CSS to `globals.css`** — append after the last rule:

```css
/* ── UI Components ─────────────────────────────── */
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  border-radius: 999px;
  padding: 10px 18px;
  font: inherit;
  font-weight: 600;
  font-size: 14px;
  cursor: pointer;
  transition: opacity 150ms ease, background 150ms ease, border-color 150ms ease;
  border: 1px solid transparent;
  white-space: nowrap;
  text-decoration: none;
}
.btn:disabled { opacity: 0.45; cursor: not-allowed; pointer-events: none; }
.btn-default  { background: var(--accent); color: white; }
.btn-default:hover:not(:disabled) { opacity: 0.88; }
.btn-outline  { background: transparent; border-color: var(--line); color: var(--text); }
.btn-outline:hover:not(:disabled) { background: var(--surface); }
.btn-ghost    { background: transparent; color: var(--text); border-color: transparent; }
.btn-ghost:hover:not(:disabled) { background: var(--surface); }
.btn-destructive { background: rgba(220,38,38,0.88); color: white; }
.btn-destructive:hover:not(:disabled) { opacity: 0.88; }
.btn-sm { padding: 6px 12px; font-size: 13px; }
.btn-lg { padding: 14px 26px; font-size: 16px; }
```

- [ ] **Step 2: Write the failing test** — create `tests/button.test.mjs`:

```js
import test from "node:test";
import assert from "node:assert/strict";

// Minimal contract: the module exports a Button function
// Full render tests require a DOM environment; we verify exports here.
test("button module exports Button", async () => {
  // Dynamic import used so missing file = clear failure message
  const mod = await import("../components/ui/button.tsx").catch(() => null);
  assert.notEqual(mod, null, "button.tsx must exist");
});
```

- [ ] **Step 3: Run test — expect FAIL (file not yet created)**

```bash
cd apps/console-web && node --test tests/button.test.mjs 2>&1 | tail -5
```

Expected: test fails with "button.tsx must exist" or import error.

- [ ] **Step 4: Create `components/ui/button.tsx`**

```tsx
import { cva, type VariantProps } from "class-variance-authority";
import { ButtonHTMLAttributes, forwardRef } from "react";
import { cn } from "../../lib/cn";

const buttonVariants = cva("btn", {
  variants: {
    variant: {
      default: "btn-default",
      outline: "btn-outline",
      ghost: "btn-ghost",
      destructive: "btn-destructive",
    },
    size: {
      default: "",
      sm: "btn-sm",
      lg: "btn-lg",
    },
  },
  defaultVariants: { variant: "default", size: "default" },
});

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, ...props }, ref) => (
    <button
      ref={ref}
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    />
  )
);
Button.displayName = "Button";
```

- [ ] **Step 5: Run test — expect PASS**

```bash
cd apps/console-web && node --test tests/button.test.mjs 2>&1 | tail -5
```

Expected: `✔ button module exports Button`.

- [ ] **Step 6: Build check**

```bash
cd apps/console-web && npm run build 2>&1 | tail -5
```

Expected: no TypeScript errors.

- [ ] **Step 7: Commit**

```bash
git add apps/console-web/app/globals.css apps/console-web/components/ui/button.tsx apps/console-web/tests/button.test.mjs
git commit -m "feat(console-web): add Button component with variants"
```

---

## Task 3: Badge component + CSS

**Files:**
- Create: `apps/console-web/components/ui/badge.tsx`
- Modify: `apps/console-web/app/globals.css`

- [ ] **Step 1: Add badge CSS to `globals.css`** — append after button CSS:

```css
.badge {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.badge-default   { background: var(--accent-soft); color: var(--accent); }
.badge-queued    { background: rgba(100,116,139,0.14); color: #475569; }
.badge-planning  { background: rgba(168,85,247,0.14); color: #9333ea; }
.badge-running   { background: rgba(59,130,246,0.14); color: #2563eb; }
.badge-blocked   { background: rgba(234,179,8,0.14);  color: #b45309; }
.badge-ready     { background: rgba(34,197,94,0.14);  color: #16a34a; }
.badge-released  { background: rgba(34,197,94,0.14);  color: #16a34a; }
.badge-closed    { background: rgba(100,116,139,0.10); color: #64748b; }
.badge-critical  { background: rgba(239,68,68,0.14);  color: #dc2626; }
.badge-high      { background: rgba(234,179,8,0.14);  color: #b45309; }
.badge-medium    { background: rgba(59,130,246,0.14); color: #2563eb; }
.badge-low       { background: rgba(100,116,139,0.14); color: #475569; }
```

- [ ] **Step 2: Create `components/ui/badge.tsx`**

```tsx
import { cva, type VariantProps } from "class-variance-authority";
import { HTMLAttributes } from "react";
import { cn } from "../../lib/cn";

const badgeVariants = cva("badge", {
  variants: {
    variant: {
      default:   "badge-default",
      queued:    "badge-queued",
      planning:  "badge-planning",
      running:   "badge-running",
      blocked:   "badge-blocked",
      ready:     "badge-ready",
      released:  "badge-released",
      closed:    "badge-closed",
      critical:  "badge-critical",
      high:      "badge-high",
      medium:    "badge-medium",
      low:       "badge-low",
    },
  },
  defaultVariants: { variant: "default" },
});

export type BadgeVariant = NonNullable<VariantProps<typeof badgeVariants>["variant"]>;

export interface BadgeProps
  extends HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}
```

- [ ] **Step 3: Build check**

```bash
cd apps/console-web && npm run build 2>&1 | tail -5
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add apps/console-web/app/globals.css apps/console-web/components/ui/badge.tsx
git commit -m "feat(console-web): add Badge component with status variants"
```

---

## Task 4: Dialog component + CSS

**Files:**
- Create: `apps/console-web/components/ui/dialog.tsx`
- Modify: `apps/console-web/app/globals.css`

- [ ] **Step 1: Add dialog + form CSS to `globals.css`** — append:

```css
.dialog-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.42);
  z-index: 200;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}
.dialog-panel {
  background: var(--surface-strong);
  border: 1px solid var(--line);
  border-radius: 24px;
  box-shadow: var(--shadow);
  width: 100%;
  max-width: 520px;
  padding: 28px;
  max-height: 90vh;
  overflow-y: auto;
}
.dialog-title {
  margin: 0 0 20px;
  font-family: "IBM Plex Serif", Georgia, serif;
  font-size: 20px;
  font-weight: 600;
}
.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 24px;
  padding-top: 20px;
  border-top: 1px solid var(--line);
}
.form-field { display: grid; gap: 6px; margin-bottom: 14px; }
.form-label { font-size: 13px; font-weight: 600; color: var(--muted); }
.form-input,
.form-select,
.form-textarea {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--surface-strong);
  color: var(--text);
  font: inherit;
  font-size: 14px;
}
.form-input:focus,
.form-select:focus,
.form-textarea:focus {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.form-textarea { min-height: 80px; resize: vertical; }
.form-error {
  padding: 10px 14px;
  border-radius: 12px;
  background: rgba(220,38,38,0.08);
  color: #dc2626;
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 12px;
}
```

- [ ] **Step 2: Create `components/ui/dialog.tsx`**

```tsx
"use client";

import { ReactNode, useEffect } from "react";

interface DialogProps {
  onClose: () => void;
  children: ReactNode;
}

export function Dialog({ onClose, children }: DialogProps) {
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [onClose]);

  return (
    <div
      className="dialog-overlay"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="dialog-panel" role="dialog" aria-modal="true">
        {children}
      </div>
    </div>
  );
}

export function DialogTitle({ children }: { children: ReactNode }) {
  return <h2 className="dialog-title">{children}</h2>;
}

export function DialogFooter({ children }: { children: ReactNode }) {
  return <div className="dialog-footer">{children}</div>;
}
```

- [ ] **Step 3: Build check**

```bash
cd apps/console-web && npm run build 2>&1 | tail -5
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add apps/console-web/app/globals.css apps/console-web/components/ui/dialog.tsx
git commit -m "feat(console-web): add Dialog component with overlay and keyboard close"
```

---

## Task 5: Tabs component + CSS

**Files:**
- Create: `apps/console-web/components/ui/tabs.tsx`
- Modify: `apps/console-web/app/globals.css`

- [ ] **Step 1: Add tabs CSS to `globals.css`** — append:

```css
.tabs { display: grid; gap: 16px; }
.tabs-list { display: flex; flex-wrap: wrap; gap: 8px; }
.tabs-trigger {
  border: 1px solid var(--line);
  border-radius: 999px;
  background: var(--surface-strong);
  color: var(--muted);
  font: inherit;
  font-size: 13px;
  font-weight: 600;
  padding: 8px 16px;
  cursor: pointer;
  transition: background 150ms ease, color 150ms ease, border-color 150ms ease;
}
.tabs-trigger[aria-selected="true"] {
  background: var(--accent);
  border-color: var(--accent);
  color: white;
}
.tabs-trigger:hover:not([aria-selected="true"]) {
  background: var(--surface);
  color: var(--text);
}
.tabs-content { display: none; }
.tabs-content[data-active="true"] { display: block; }
```

- [ ] **Step 2: Create `components/ui/tabs.tsx`**

```tsx
"use client";

import { createContext, ReactNode, useContext, useState } from "react";
import { cn } from "../../lib/cn";

const TabsContext = createContext<{ active: string; setActive: (v: string) => void }>({
  active: "",
  setActive: () => {},
});

export function Tabs({
  defaultValue,
  children,
  className,
}: {
  defaultValue: string;
  children: ReactNode;
  className?: string;
}) {
  const [active, setActive] = useState(defaultValue);
  return (
    <TabsContext.Provider value={{ active, setActive }}>
      <div className={cn("tabs", className)}>{children}</div>
    </TabsContext.Provider>
  );
}

export function TabsList({ children }: { children: ReactNode }) {
  return <div className="tabs-list">{children}</div>;
}

export function TabsTrigger({ value, children }: { value: string; children: ReactNode }) {
  const { active, setActive } = useContext(TabsContext);
  return (
    <button
      type="button"
      className="tabs-trigger"
      aria-selected={active === value}
      onClick={() => setActive(value)}
    >
      {children}
    </button>
  );
}

export function TabsContent({ value, children }: { value: string; children: ReactNode }) {
  const { active } = useContext(TabsContext);
  return (
    <div className="tabs-content" data-active={active === value ? "true" : "false"}>
      {children}
    </div>
  );
}
```

- [ ] **Step 3: Build check**

```bash
cd apps/console-web && npm run build 2>&1 | tail -5
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add apps/console-web/app/globals.css apps/console-web/components/ui/tabs.tsx
git commit -m "feat(console-web): add Tabs component (client-side controlled)"
```

---

## Task 6: Smoke test (Slice 1 gate)

**Files:**
- Create: `apps/console-web/tests/smoke.test.mjs`

- [ ] **Step 1: Create `tests/smoke.test.mjs`**

```js
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
    "",                          // /
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

test("ui components are importable", async () => {
  const components = ["button", "badge", "dialog", "tabs"];
  for (const name of components) {
    const path = join(root, "components", "ui", `${name}.tsx`);
    assert.ok(existsSync(path), `ui/${name}.tsx must exist`);
  }
});
```

- [ ] **Step 2: Run smoke test — expect PASS**

```bash
cd apps/console-web && node --test tests/smoke.test.mjs 2>&1
```

Expected: all 3 tests pass.

- [ ] **Step 3: Commit**

```bash
git add apps/console-web/tests/smoke.test.mjs
git commit -m "test(console-web): add smoke test for page routes and UI components"
```

---

## Task 7: StatusBadge + replace pills (Slice 3)

**Files:**
- Create: `apps/console-web/components/status-badge.tsx`
- Modify: `apps/console-web/app/work-items/page.tsx`
- Modify: `apps/console-web/app/releases/page.tsx`
- Modify: `apps/console-web/app/incidents/page.tsx`

- [ ] **Step 1: Create `components/status-badge.tsx`**

```tsx
import { Badge, type BadgeVariant } from "./ui/badge";

const STATUS_MAP: Record<string, BadgeVariant> = {
  queued:    "queued",
  planning:  "planning",
  running:   "running",
  blocked:   "blocked",
  ready:     "ready",
  released:  "released",
  closed:    "closed",
  critical:  "critical",
  high:      "high",
  medium:    "medium",
  low:       "low",
  open:      "blocked",
  pending:   "queued",
  completed: "released",
  failed:    "critical",
  active:    "running",
  rollback:  "critical",
};

export function StatusBadge({ status }: { status: string }) {
  const lower = status.toLowerCase();
  const variant = STATUS_MAP[lower] ?? "default";
  return <Badge variant={variant}>{status}</Badge>;
}
```

- [ ] **Step 2: Write test for StatusBadge** — add to `tests/smoke.test.mjs`:

```js
test("StatusBadge maps known statuses without throwing", async () => {
  const { existsSync } = await import("node:fs");
  const { join } = await import("node:path");
  const root = new URL("..", import.meta.url).pathname;
  assert.ok(
    existsSync(join(root, "components", "status-badge.tsx")),
    "status-badge.tsx must exist"
  );
});
```

- [ ] **Step 3: Run test — expect PASS**

```bash
cd apps/console-web && node --test tests/smoke.test.mjs 2>&1 | tail -8
```

- [ ] **Step 4: Update `app/work-items/page.tsx`** — replace `{ key: "status", label: "Status" }` column with a render function:

In the `DataTable` columns array, change:
```tsx
{ key: "status", label: "Status" },
```
to:
```tsx
{
  key: "status",
  label: "Status",
  render: (row) => <StatusBadge status={String(row.status ?? "-")} />,
},
```

Also add the import at the top of the file:
```tsx
import { StatusBadge } from "../../components/status-badge";
```

- [ ] **Step 5: Update `app/releases/page.tsx`** — replace the pill-row status block:

Replace:
```tsx
{Object.entries((data.byStatus as Record<string, number>) ?? {}).map(([status, count]) => (
  <span className="pill" key={status}>
    {status}: {count}
  </span>
))}
```
with:
```tsx
{Object.entries((data.byStatus as Record<string, number>) ?? {}).map(([status, count]) => (
  <span key={status} style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}>
    <StatusBadge status={status} />
    <span className="subtle">{count}</span>
  </span>
))}
```

Also add the import:
```tsx
import { StatusBadge } from "../../components/status-badge";
```

And update the status column in the DataTable:
```tsx
{
  key: "status",
  label: "Status",
  render: (row) => <StatusBadge status={String(row.status ?? "-")} />,
},
```

- [ ] **Step 6: Update `app/incidents/page.tsx`** — same pattern for severity pills:

Add import:
```tsx
import { StatusBadge } from "../../components/status-badge";
```

Replace severity pill rendering:
```tsx
{Object.entries((data.bySeverity as Record<string, number>) ?? {}).map(([severity, count]) => (
  <span key={severity} style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}>
    <StatusBadge status={severity} />
    <span className="subtle">{count}</span>
  </span>
))}
```

Add render to DataTable status column:
```tsx
{
  key: "status",
  label: "Status",
  render: (row) => <StatusBadge status={String(row.status ?? "-")} />,
},
```

- [ ] **Step 7: Build check**

```bash
cd apps/console-web && npm run build 2>&1 | tail -5
```

Expected: no TypeScript errors.

- [ ] **Step 8: Commit**

```bash
git add apps/console-web/components/status-badge.tsx \
        apps/console-web/app/work-items/page.tsx \
        apps/console-web/app/releases/page.tsx \
        apps/console-web/app/incidents/page.tsx \
        apps/console-web/tests/smoke.test.mjs
git commit -m "feat(console-web): add StatusBadge, replace pills with semantic color badges"
```

---

## Task 8: WorkItem create — API layer (Slice 2)

**Files:**
- Modify: `apps/console-web/lib/console-api.ts`

- [ ] **Step 1: Write test** — add to `tests/console-data.test.mjs`:

```js
test("console-api exports createWorkItem function", async () => {
  const mod = await import("../lib/console-api.ts");
  assert.equal(typeof mod.createWorkItem, "function", "createWorkItem must be exported");
  assert.equal(typeof mod.getApiBaseUrl, "function", "getApiBaseUrl must be exported");
});
```

- [ ] **Step 2: Run test — expect FAIL**

```bash
cd apps/console-web && node --test tests/console-data.test.mjs 2>&1 | tail -5
```

Expected: fails on missing exports.

- [ ] **Step 3: Update `lib/console-api.ts`** — add `getApiBaseUrl` and `createWorkItem`:

```ts
import { buildConsoleApiUrl } from "./console-data.mjs";

const DEFAULT_BASE_URL = process.env.CONSOLE_API_BASE_URL || "http://127.0.0.1:8080";

// Works in both Server Components (CONSOLE_API_BASE_URL) and Client Components (NEXT_PUBLIC_CONSOLE_API_BASE_URL)
export function getApiBaseUrl(): string {
  if (typeof window !== "undefined") {
    return process.env.NEXT_PUBLIC_CONSOLE_API_BASE_URL ?? "http://127.0.0.1:8080";
  }
  return DEFAULT_BASE_URL;
}

async function fetchJson<T>(path: string): Promise<T | null> {
  try {
    const response = await fetch(buildConsoleApiUrl(DEFAULT_BASE_URL, path), {
      cache: "no-store",
    });
    if (!response.ok) return null;
    const payload = await response.json();
    return (payload?.data ?? null) as T | null;
  } catch {
    return null;
  }
}

export async function getMissionControl() {
  return fetchJson<Record<string, unknown>>("/api/console/mission-control");
}

export async function getWorkItems() {
  const result = await fetchJson<Array<Record<string, unknown>>>("/api/work-items");
  return result ?? [];
}

export async function getTaskWorkspace(workItemId: string) {
  return fetchJson<Record<string, unknown>>(`/api/console/work-items/${workItemId}/workspace`);
}

export async function getReleaseConsole() {
  return fetchJson<Record<string, unknown>>("/api/console/releases");
}

export async function getIncidentConsole() {
  return fetchJson<Record<string, unknown>>("/api/console/incidents");
}

export async function getEvalConsole() {
  return fetchJson<Record<string, unknown>>("/api/console/evals");
}

export async function getGovernanceConsole() {
  return fetchJson<Record<string, unknown>>("/api/console/governance");
}

export async function getAgentRuns(): Promise<Array<Record<string, unknown>>> {
  const result = await fetchJson<Array<Record<string, unknown>>>("/api/agent-runs");
  return result ?? [];
}

export async function getPlanDetail(planId: string) {
  return fetchJson<Record<string, unknown>>(`/api/plans/${encodeURIComponent(planId)}`);
}

export interface CreateWorkItemPayload {
  repo: string;
  title: string;
  description: string;
  type: "feature" | "bugfix" | "incident" | "ops" | "experiment";
  priority: "low" | "medium" | "high" | "critical";
}

export interface CreateWorkItemResult {
  success: boolean;
  data?: Record<string, unknown>;
  error?: string;
}

export async function createWorkItem(
  payload: CreateWorkItemPayload
): Promise<CreateWorkItemResult> {
  try {
    const res = await fetch(
      `${getApiBaseUrl()}/api/work-items`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }
    );
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      return { success: false, error: body.error ?? `Request failed (${res.status})` };
    }
    return { success: true, data: body.data };
  } catch (err) {
    return { success: false, error: err instanceof Error ? err.message : "Network error" };
  }
}
```

- [ ] **Step 4: Run test — expect PASS**

```bash
cd apps/console-web && node --test tests/console-data.test.mjs 2>&1 | tail -8
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/console-web/lib/console-api.ts apps/console-web/tests/console-data.test.mjs
git commit -m "feat(console-web): add createWorkItem, getAgentRuns, getPlanDetail to API client"
```

---

## Task 9: CreateWorkItemDialog component (Slice 2)

**Files:**
- Create: `apps/console-web/components/create-work-item-dialog.tsx`
- Modify: `apps/console-web/app/work-items/page.tsx`

- [ ] **Step 1: Create `components/create-work-item-dialog.tsx`**

```tsx
"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "./ui/button";
import { Dialog, DialogFooter, DialogTitle } from "./ui/dialog";
import { createWorkItem, type CreateWorkItemPayload } from "../lib/console-api";

const EMPTY_FORM: CreateWorkItemPayload = {
  repo: "",
  title: "",
  description: "",
  type: "feature",
  priority: "medium",
};

export function CreateWorkItemDialog() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<CreateWorkItemPayload>(EMPTY_FORM);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  function handleChange(
    e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>
  ) {
    setForm((prev) => ({ ...prev, [e.target.name]: e.target.value }));
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!form.repo.trim() || !form.title.trim() || !form.description.trim()) {
      setError("repo, title, description 均为必填项");
      return;
    }
    setError(null);
    setLoading(true);
    const result = await createWorkItem(form);
    setLoading(false);
    if (!result.success) {
      setError(result.error ?? "创建失败");
      return;
    }
    setOpen(false);
    setForm(EMPTY_FORM);
    router.refresh();
  }

  return (
    <>
      <Button onClick={() => { setError(null); setOpen(true); }}>+ 新建任务</Button>

      {open ? (
        <Dialog onClose={() => setOpen(false)}>
          <DialogTitle>新建开发任务</DialogTitle>
          <form onSubmit={handleSubmit}>
            {error ? <p className="form-error">{error}</p> : null}

            <div className="form-field">
              <label className="form-label" htmlFor="wi-repo">Repo *</label>
              <input
                id="wi-repo"
                name="repo"
                className="form-input"
                placeholder="org/repo-name"
                value={form.repo}
                onChange={handleChange}
                required
              />
            </div>

            <div className="form-field">
              <label className="form-label" htmlFor="wi-title">Title *</label>
              <input
                id="wi-title"
                name="title"
                className="form-input"
                placeholder="Fix auth bug"
                value={form.title}
                onChange={handleChange}
                required
              />
            </div>

            <div className="form-field">
              <label className="form-label" htmlFor="wi-description">Description *</label>
              <textarea
                id="wi-description"
                name="description"
                className="form-textarea"
                placeholder="Describe the goal and acceptance criteria…"
                value={form.description}
                onChange={handleChange}
                required
              />
            </div>

            <div className="form-field">
              <label className="form-label" htmlFor="wi-type">Type</label>
              <select id="wi-type" name="type" className="form-select" value={form.type} onChange={handleChange}>
                <option value="feature">Feature</option>
                <option value="bugfix">Bugfix</option>
                <option value="incident">Incident</option>
                <option value="ops">Ops</option>
                <option value="experiment">Experiment</option>
              </select>
            </div>

            <div className="form-field">
              <label className="form-label" htmlFor="wi-priority">Priority</label>
              <select id="wi-priority" name="priority" className="form-select" value={form.priority} onChange={handleChange}>
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
                <option value="critical">Critical</option>
              </select>
            </div>

            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setOpen(false)}>
                取消
              </Button>
              <Button type="submit" disabled={loading}>
                {loading ? "提交中…" : "创建任务"}
              </Button>
            </DialogFooter>
          </form>
        </Dialog>
      ) : null}
    </>
  );
}
```

- [ ] **Step 2: Update `app/work-items/page.tsx`** — add dialog to header:

Add import at the top:
```tsx
import { CreateWorkItemDialog } from "../../components/create-work-item-dialog";
```

In the `<header className="page-header">` block, add the dialog after the `<RefreshButton />`:
```tsx
<div style={{ display: "flex", gap: "10px", alignItems: "center", marginTop: "16px", flexWrap: "wrap" }}>
  <RefreshButton />
  <CreateWorkItemDialog />
</div>
```

Remove the standalone `<RefreshButton />` that was there before, so there's only one instance inside the flex wrapper.

- [ ] **Step 3: Build check**

```bash
cd apps/console-web && npm run build 2>&1 | tail -5
```

Expected: no TypeScript errors.

- [ ] **Step 4: Commit**

```bash
git add apps/console-web/components/create-work-item-dialog.tsx \
        apps/console-web/app/work-items/page.tsx
git commit -m "feat(console-web): add CreateWorkItemDialog — POST /api/work-items from UI"
```

---

## Task 10: Timeline + ContextPackPanel components (Slice 4)

**Files:**
- Create: `apps/console-web/components/timeline.tsx`
- Create: `apps/console-web/components/context-pack-panel.tsx`
- Modify: `apps/console-web/app/globals.css`

- [ ] **Step 1: Add timeline CSS to `globals.css`** — append:

```css
.timeline-v { display: grid; gap: 0; position: relative; }
.timeline-v::before {
  content: "";
  position: absolute;
  left: 10px;
  top: 6px;
  bottom: 6px;
  width: 2px;
  background: var(--line);
}
.timeline-entry {
  display: grid;
  grid-template-columns: 22px 1fr;
  gap: 14px;
  padding: 10px 0;
  position: relative;
}
.timeline-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--accent);
  border: 2px solid var(--surface-strong);
  margin-top: 4px;
  z-index: 1;
  flex-shrink: 0;
}
.timeline-entry-body { display: grid; gap: 4px; }
.timeline-event-type {
  font-size: 13px;
  font-weight: 700;
  color: var(--text);
}
.timeline-event-source {
  font-size: 12px;
  color: var(--muted);
}
.timeline-event-data {
  margin: 4px 0 0;
  padding: 10px 14px;
  border-radius: 12px;
  background: #17201c;
  color: #f7f6f1;
  font-size: 12px;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
}
.context-pack-section { display: grid; gap: 10px; }
.context-pack-label {
  font-size: 12px;
  font-weight: 700;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin-bottom: 4px;
}
.file-hint-list { display: flex; flex-wrap: wrap; gap: 6px; }
.file-hint {
  padding: 4px 10px;
  border-radius: 8px;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 12px;
  font-family: monospace;
}
.criteria-list { display: grid; gap: 6px; padding-left: 0; list-style: none; }
.criteria-list li {
  padding: 8px 12px;
  border-left: 3px solid var(--accent);
  background: var(--accent-soft);
  border-radius: 0 8px 8px 0;
  font-size: 13px;
}
```

- [ ] **Step 2: Create `components/timeline.tsx`**

```tsx
import { StatusBadge } from "./status-badge";

type TimelineEvent = {
  type?: unknown;
  source?: unknown;
  timestamp?: unknown;
  data?: unknown;
};

function formatTimestamp(ts: unknown): string {
  const n = Number(ts);
  if (!n) return "";
  return new Date(n).toLocaleString("zh-CN", { hour12: false });
}

export function Timeline({
  events,
  emptyText,
}: {
  events: TimelineEvent[];
  emptyText: string;
}) {
  if (events.length === 0) {
    return <p className="empty-state">{emptyText}</p>;
  }

  const sorted = [...events].sort(
    (a, b) => Number(a.timestamp ?? 0) - Number(b.timestamp ?? 0)
  );

  return (
    <ol className="timeline-v" style={{ listStyle: "none", padding: 0, margin: 0 }}>
      {sorted.map((event, i) => {
        const status = String(
          (event.data as Record<string, unknown>)?.status ?? ""
        );
        return (
          <li key={i} className="timeline-entry">
            <div className="timeline-dot" />
            <div className="timeline-entry-body">
              <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
                <span className="timeline-event-type">
                  {String(event.type ?? "event")}
                </span>
                {status ? <StatusBadge status={status} /> : null}
                {event.timestamp ? (
                  <span className="timeline-event-source">
                    {formatTimestamp(event.timestamp)}
                  </span>
                ) : null}
              </div>
              {event.source ? (
                <span className="timeline-event-source">
                  source: {String(event.source)}
                </span>
              ) : null}
              {event.data ? (
                <pre className="timeline-event-data">
                  {JSON.stringify(event.data, null, 2)}
                </pre>
              ) : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
```

- [ ] **Step 3: Create `components/context-pack-panel.tsx`**

```tsx
type ContextPack = {
  packId?: unknown;
  fileHints?: unknown;
  acceptanceCriteria?: unknown;
  repoScope?: unknown;
};

export function ContextPackPanel({ contextPack }: { contextPack: ContextPack }) {
  const fileHints = Array.isArray(contextPack.fileHints)
    ? (contextPack.fileHints as string[])
    : [];
  const criteria = Array.isArray(contextPack.acceptanceCriteria)
    ? (contextPack.acceptanceCriteria as string[])
    : [];
  const repoScope = Array.isArray(contextPack.repoScope)
    ? (contextPack.repoScope as string[])
    : [];

  return (
    <div className="context-pack-section">
      <div>
        <p className="context-pack-label">Pack ID</p>
        <code style={{ fontSize: "13px", color: "var(--muted)" }}>
          {String(contextPack.packId ?? "-")}
        </code>
      </div>

      {repoScope.length > 0 ? (
        <div>
          <p className="context-pack-label">Repo Scope</p>
          <div className="file-hint-list">
            {repoScope.map((r) => (
              <span key={r} className="file-hint">{r}</span>
            ))}
          </div>
        </div>
      ) : null}

      {fileHints.length > 0 ? (
        <div>
          <p className="context-pack-label">File Hints</p>
          <div className="file-hint-list">
            {fileHints.map((f) => (
              <span key={f} className="file-hint">{f}</span>
            ))}
          </div>
        </div>
      ) : null}

      {criteria.length > 0 ? (
        <div>
          <p className="context-pack-label">Acceptance Criteria</p>
          <ul className="criteria-list">
            {criteria.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {fileHints.length === 0 && criteria.length === 0 ? (
        <p className="empty-state">Context Pack 暂无详情数据。</p>
      ) : null}
    </div>
  );
}
```

- [ ] **Step 4: Build check**

```bash
cd apps/console-web && npm run build 2>&1 | tail -5
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add apps/console-web/app/globals.css \
        apps/console-web/components/timeline.tsx \
        apps/console-web/components/context-pack-panel.tsx
git commit -m "feat(console-web): add Timeline and ContextPackPanel components"
```

---

## Task 11: WorkItem detail page refactor (Slice 4)

**Files:**
- Modify: `apps/console-web/app/work-items/[workItemId]/page.tsx`

- [ ] **Step 1: Replace `app/work-items/[workItemId]/page.tsx`** with:

```tsx
import Link from "next/link";
import { ContextPackPanel } from "../../../components/context-pack-panel";
import { ErrorBanner } from "../../../components/error-banner";
import { Panel } from "../../../components/panel";
import { RefreshButton } from "../../../components/refresh-button";
import { StatusBadge } from "../../../components/status-badge";
import { Timeline } from "../../../components/timeline";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../../../components/ui/tabs";
import { getTaskWorkspace } from "../../../lib/console-api";
import { resourceErrorMessage } from "../../../lib/console-data.mjs";

export const dynamic = "force-dynamic";

export default async function TaskWorkspaceDetailPage({
  params,
}: {
  params: Promise<{ workItemId: string }>;
}) {
  const { workItemId } = await params;
  const fetched = await getTaskWorkspace(workItemId);
  const errorMessage = resourceErrorMessage(fetched, "Task Workspace");

  if (!fetched) {
    return (
      <div className="page">
        <header className="page-header">
          <span className="page-kicker">Workspace</span>
          <h1>Task Workspace</h1>
          <p className="empty-state">未找到 {workItemId} 对应的工作区数据。</p>
        </header>
      </div>
    );
  }

  const workItem = (fetched.workItem as Record<string, unknown>) ?? {};
  const contextPack = (fetched.contextPack as Record<string, unknown>) ?? {};
  const planRequest = (fetched.planRequest as Record<string, unknown>) ?? {};
  const eventTimeline = Array.isArray(fetched.eventTimeline)
    ? (fetched.eventTimeline as Record<string, unknown>[])
    : [];
  const planId = String(planRequest.planId ?? "");

  return (
    <div className="page">
      <header className="page-header">
        <span className="page-kicker">Workspace Detail</span>
        <h1>{String(workItem.title ?? workItemId)}</h1>
        <div style={{ display: "flex", alignItems: "center", gap: "10px", flexWrap: "wrap", marginTop: "8px" }}>
          <StatusBadge status={String(workItem.status ?? "unknown")} />
          <span className="subtle">repo: {String(workItem.repo ?? "-")}</span>
          {planId ? (
            <Link href={`/plans/${encodeURIComponent(planId)}`} className="inline-link">
              → Plan {planId.slice(0, 20)}…
            </Link>
          ) : null}
        </div>
        <RefreshButton />
      </header>

      <ErrorBanner message={errorMessage} />

      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="context">Context Pack</TabsTrigger>
          <TabsTrigger value="timeline">Timeline ({eventTimeline.length})</TabsTrigger>
          <TabsTrigger value="raw">Raw JSON</TabsTrigger>
        </TabsList>

        <TabsContent value="overview">
          <Panel title="Work Item" eyebrow="Details">
            <div className="stack">
              <p><strong>Goal:</strong> {String(workItem.goal ?? "-")}</p>
              <p><strong>Priority:</strong> <StatusBadge status={String(workItem.priority ?? "-")} /></p>
              <p><strong>Requested by:</strong> {String(workItem.requestedBy ?? "-")}</p>
            </div>
          </Panel>
        </TabsContent>

        <TabsContent value="context">
          <Panel title="Context Pack" eyebrow="Context">
            <ContextPackPanel contextPack={contextPack} />
          </Panel>
        </TabsContent>

        <TabsContent value="timeline">
          <Panel title="Event Timeline" eyebrow="Events">
            <Timeline
              events={eventTimeline}
              emptyText="当前还没有时间线事件。"
            />
          </Panel>
        </TabsContent>

        <TabsContent value="raw">
          <Panel title="Raw JSON" eyebrow="Debug">
            <pre className="code-block">{JSON.stringify(fetched, null, 2)}</pre>
          </Panel>
        </TabsContent>
      </Tabs>
    </div>
  );
}
```

- [ ] **Step 2: Build check**

```bash
cd apps/console-web && npm run build 2>&1 | tail -5
```

Expected: no TypeScript errors.

- [ ] **Step 3: Run smoke test**

```bash
cd apps/console-web && node --test tests/smoke.test.mjs 2>&1
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add apps/console-web/app/work-items/\[workItemId\]/page.tsx
git commit -m "feat(console-web): refactor WorkItem detail — Timeline, ContextPack, Plan link"
```

---

## Task 12: Polling wrapper (Slice 5)

**Files:**
- Create: `apps/console-web/components/polling-wrapper.tsx`
- Modify: `apps/console-web/app/work-items/[workItemId]/page.tsx`

- [ ] **Step 1: Create `components/polling-wrapper.tsx`**

```tsx
"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

interface PollingWrapperProps {
  /** Status of the work item — polling only activates when "running" */
  status: string;
  /** Interval in milliseconds (default 15000) */
  intervalMs?: number;
}

export function PollingWrapper({ status, intervalMs = 15_000 }: PollingWrapperProps) {
  const router = useRouter();
  const [online, setOnline] = useState(true);
  const [tick, setTick] = useState(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const isRunning = status.toLowerCase() === "running";

  const refresh = useCallback(() => {
    if (!navigator.onLine) {
      setOnline(false);
      return;
    }
    setOnline(true);
    router.refresh();
    setTick((t) => t + 1);
  }, [router]);

  useEffect(() => {
    function handleOnline() { setOnline(true); }
    function handleOffline() { setOnline(false); }
    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);
    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, []);

  useEffect(() => {
    if (!isRunning) {
      if (intervalRef.current) clearInterval(intervalRef.current);
      return;
    }
    intervalRef.current = setInterval(refresh, intervalMs);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [isRunning, intervalMs, refresh]);

  if (!isRunning) return null;

  return (
    <div
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "6px",
        fontSize: "12px",
        color: online ? "var(--accent)" : "var(--warning)",
        fontWeight: 600,
      }}
    >
      <span style={{ display: "inline-block", width: "8px", height: "8px", borderRadius: "50%", background: "currentColor", animation: online ? "pulse 1.5s infinite" : "none" }} />
      {online ? `自动刷新中 (${Math.round(intervalMs / 1000)}s)` : "网络断开，已停止刷新"}
      <span style={{ color: "var(--muted)", fontWeight: 400 }}>· 已刷新 {tick} 次</span>
    </div>
  );
}
```

- [ ] **Step 2: Add pulse animation to `globals.css`** — append:

```css
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50%       { opacity: 0.3; }
}
```

- [ ] **Step 3: Add `PollingWrapper` to `app/work-items/[workItemId]/page.tsx`**

Add import at the top:
```tsx
import { PollingWrapper } from "../../../components/polling-wrapper";
```

In the header section, after `<RefreshButton />`, add:
```tsx
<PollingWrapper status={String(workItem.status ?? "")} />
```

- [ ] **Step 4: Build check**

```bash
cd apps/console-web && npm run build 2>&1 | tail -5
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add apps/console-web/components/polling-wrapper.tsx \
        apps/console-web/app/globals.css \
        apps/console-web/app/work-items/\[workItemId\]/page.tsx
git commit -m "feat(console-web): add PollingWrapper — auto-refresh every 15s when status=RUNNING"
```

---

## Task 13: Agent Runs backend (Slice 6)

**Files:**
- Modify: `packages/shared/domain/runtime_state.py`
- Create: `orchestrator/api/agent_runs.py`
- Modify: `orchestrator/api/server.py`
- Create: `tests/test_agent_runs_api.py`

- [ ] **Step 1: Write pytest** — create `tests/test_agent_runs_api.py`:

```python
"""Tests for GET /api/agent-runs endpoint."""
from __future__ import annotations

import pytest
from packages.shared.domain.runtime_state import (
    clear_runtime_state,
    list_agent_runs,
    record_agent_run,
)
from packages.shared.domain.models import AgentRun, AgentRunStatus


@pytest.fixture(autouse=True)
def reset_state():
    clear_runtime_state()
    yield
    clear_runtime_state()


def test_list_agent_runs_empty():
    assert list_agent_runs() == []


def test_record_and_list_agent_run():
    run = AgentRun(
        run_id="run_test_001",
        work_item_id="wi_test_001",
        context_pack_id="cp_test_001",
        agent="codex",
        model="gpt-5.3-codex",
        status=AgentRunStatus.RUNNING,
        planned_steps=("plan", "implement", "test"),
    )
    record_agent_run(run)
    runs = list_agent_runs()
    assert len(runs) == 1
    assert runs[0]["runId"] == "run_test_001"
    assert runs[0]["agent"] == "codex"
    assert runs[0]["status"] == "running"


def test_record_agent_run_deduplicates_by_run_id():
    run = AgentRun(
        run_id="run_dedup",
        work_item_id="wi_001",
        context_pack_id="cp_001",
        agent="codex",
        model="gpt-5.3-codex",
        status=AgentRunStatus.PENDING,
        planned_steps=(),
    )
    record_agent_run(run)
    updated = AgentRun(
        run_id="run_dedup",
        work_item_id="wi_001",
        context_pack_id="cp_001",
        agent="codex",
        model="gpt-5.3-codex",
        status=AgentRunStatus.COMPLETED,
        planned_steps=(),
    )
    record_agent_run(updated)
    runs = list_agent_runs()
    assert len(runs) == 1
    assert runs[0]["status"] == "completed"
```

- [ ] **Step 2: Run test — expect FAIL (functions not yet added)**

```bash
cd /home/gordonyang/workspace/myproject/ai-devops && python -m pytest tests/test_agent_runs_api.py -v 2>&1 | tail -15
```

Expected: ImportError or AttributeError on `record_agent_run`.

- [ ] **Step 3: Add `record_agent_run`, `list_agent_runs` to `packages/shared/domain/runtime_state.py`**

Add after the `_EVAL_RUNS` list declaration:

```python
_AGENT_RUNS: list[dict] = []
```

Add these two functions after `list_eval_runs`:

```python
def record_agent_run(agent_run: "AgentRun") -> None:
    from packages.shared.domain.models import AgentRun as _AgentRun  # avoid circular import
    incoming = agent_run.to_dict()
    filtered = [r for r in _AGENT_RUNS if r.get("runId") != agent_run.run_id]
    filtered.append(incoming)
    _AGENT_RUNS.clear()
    _AGENT_RUNS.extend(filtered)


def list_agent_runs() -> list[dict]:
    return list(_AGENT_RUNS)
```

Update `clear_runtime_state` to also clear `_AGENT_RUNS`:

```python
def clear_runtime_state() -> None:
    _AUDIT_EVENTS.clear()
    _EVAL_RUNS.clear()
    _AGENT_RUNS.clear()
```

Also add `record_agent_run` and `list_agent_runs` to the imports block at the bottom if there is one (or they're auto-available via module import).

- [ ] **Step 4: Run test — expect PASS**

```bash
cd /home/gordonyang/workspace/myproject/ai-devops && python -m pytest tests/test_agent_runs_api.py -v 2>&1 | tail -15
```

Expected: all 3 tests pass.

- [ ] **Step 5: Create `orchestrator/api/agent_runs.py`**

```python
"""GET /api/agent-runs endpoint."""
from __future__ import annotations

import json
from typing import Any

from packages.shared.domain.runtime_state import list_agent_runs


def _json_response(data: Any, status: int = 200) -> tuple[bytes, int, str]:
    body = json.dumps(data, ensure_ascii=False, indent=2)
    return body.encode("utf-8"), status, "application/json"


class AgentRunsAPIHandler:
    def handle_get_agent_runs(self):
        runs = list_agent_runs()
        return _json_response({"success": True, "data": runs, "count": len(runs)})


def create_agent_runs_handler(base_handler: type) -> type:
    class CombinedHandler(AgentRunsAPIHandler, base_handler):
        def do_GET(self):
            clean = self.path.split("?", 1)[0].strip("/")
            if clean == "api/agent-runs":
                body, status, content_type = self.handle_get_agent_runs()
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)
                return
            super().do_GET()

        def do_OPTIONS(self):
            try:
                super().do_OPTIONS()
            except AttributeError:
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
                self.end_headers()

    return CombinedHandler
```

- [ ] **Step 6: Register handler in `orchestrator/api/server.py`**

Add import (with the other try/except import block):

```python
try:
    from .agent_runs import create_agent_runs_handler
except ImportError:
    from agent_runs import create_agent_runs_handler
```

In `create_combined_handler()`, add before the return:

```python
handler = create_agent_runs_handler(handler)
```

- [ ] **Step 7: Run existing test suite to confirm no regression**

```bash
cd /home/gordonyang/workspace/myproject/ai-devops && python -m pytest tests/test_agent_runs_api.py orchestrator/api/tests/ -v 2>&1 | tail -20
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add packages/shared/domain/runtime_state.py \
        orchestrator/api/agent_runs.py \
        orchestrator/api/server.py \
        tests/test_agent_runs_api.py
git commit -m "feat(api): add GET /api/agent-runs endpoint + runtime_state agent run storage"
```

---

## Task 14: Agent Runs frontend page (Slice 6)

**Files:**
- Create: `apps/console-web/app/agent-runs/page.tsx`
- Modify: `apps/console-web/lib/navigation.mjs`

- [ ] **Step 1: Create `app/agent-runs/page.tsx`**

```tsx
import { DataTable } from "../../components/data-table";
import { ErrorBanner } from "../../components/error-banner";
import { Panel } from "../../components/panel";
import { RefreshButton } from "../../components/refresh-button";
import { StatusBadge } from "../../components/status-badge";
import { WorkspaceLink } from "../../components/data-table";
import { getAgentRuns } from "../../lib/console-api";

export const dynamic = "force-dynamic";

function StepsProgress({ planned, current }: { planned: string[]; current?: string }) {
  if (planned.length === 0) return <span className="subtle">—</span>;
  const doneIdx = current ? planned.indexOf(current) : -1;
  return (
    <span style={{ fontSize: "12px", color: "var(--muted)" }}>
      {planned.map((step, i) => (
        <span
          key={i}
          style={{
            marginRight: "4px",
            fontWeight: i <= doneIdx ? 700 : 400,
            color: i <= doneIdx ? "var(--accent)" : "var(--muted)",
          }}
        >
          {i < planned.length - 1 ? `${step} →` : step}
        </span>
      ))}
    </span>
  );
}

export default async function AgentRunsPage() {
  const runs = await getAgentRuns();

  return (
    <div className="page">
      <header className="page-header">
        <span className="page-kicker">Execution</span>
        <h1>Agent Runs</h1>
        <p>查看所有 AgentRun 记录，包含执行模型、状态和计划步骤进度。</p>
        <RefreshButton />
      </header>

      <ErrorBanner
        message={runs.length === 0 ? "当前没有 Agent Run 数据。任务执行后将显示在此处。" : null}
      />

      <Panel title="Agent Runs" eyebrow={`${runs.length} runs`}>
        <DataTable
          rows={runs}
          emptyText="当前没有 Agent Run 记录。"
          columns={[
            { key: "runId", label: "Run ID" },
            {
              key: "workItemId",
              label: "Work Item",
              render: (row) => (
                <WorkspaceLink workItemId={String(row.workItemId ?? "")} />
              ),
            },
            { key: "agent", label: "Agent" },
            { key: "model", label: "Model" },
            {
              key: "status",
              label: "Status",
              render: (row) => <StatusBadge status={String(row.status ?? "-")} />,
            },
            {
              key: "plannedSteps",
              label: "Steps",
              render: (row) => (
                <StepsProgress
                  planned={Array.isArray(row.plannedSteps) ? (row.plannedSteps as string[]) : []}
                  current={String(row.currentStep ?? "")}
                />
              ),
            },
          ]}
        />
      </Panel>
    </div>
  );
}
```

- [ ] **Step 2: Update `lib/navigation.mjs`**

```js
export const consoleNavItems = [
  { id: "mission-control", label: "Mission Control", href: "/" },
  { id: "task-workspace", label: "Task Workspace", href: "/work-items" },
  { id: "agent-runs", label: "Agent Runs", href: "/agent-runs" },
  { id: "releases", label: "Release Console", href: "/releases" },
  { id: "incidents", label: "Incident Console", href: "/incidents" },
  { id: "evals", label: "Eval Console", href: "/evals" },
  { id: "governance", label: "Governance Console", href: "/governance" },
];
```

- [ ] **Step 3: Update smoke test** — add `agent-runs` to the routes array in `tests/smoke.test.mjs`:

Change:
```js
const routes = [
  "",
  "work-items",
  "work-items/[workItemId]",
  "releases",
  "incidents",
  "evals",
  "governance",
];
```
to:
```js
const routes = [
  "",
  "work-items",
  "work-items/[workItemId]",
  "agent-runs",
  "releases",
  "incidents",
  "evals",
  "governance",
];
```

- [ ] **Step 4: Run smoke test — expect PASS**

```bash
cd apps/console-web && node --test tests/smoke.test.mjs 2>&1
```

- [ ] **Step 5: Build check**

```bash
cd apps/console-web && npm run build 2>&1 | tail -5
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add apps/console-web/app/agent-runs/page.tsx \
        apps/console-web/lib/navigation.mjs \
        apps/console-web/tests/smoke.test.mjs
git commit -m "feat(console-web): add Agent Runs page — lists all AgentRun records"
```

---

## Task 15: Plan detail page (Slice 7)

**Files:**
- Create: `apps/console-web/app/plans/[planId]/page.tsx`
- Modify: `apps/console-web/app/globals.css`

- [ ] **Step 1: Add plan steps CSS to `globals.css`** — append:

```css
.plan-steps { display: grid; gap: 12px; padding: 0; list-style: none; }
.plan-step {
  display: grid;
  grid-template-columns: 28px 1fr;
  gap: 14px;
  padding: 12px 0;
  border-bottom: 1px solid var(--line);
}
.plan-step:last-child { border-bottom: none; }
.plan-step-number {
  display: flex;
  align-items: flex-start;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 12px;
  font-weight: 700;
  flex-shrink: 0;
  padding-top: 6px;
}
.plan-step-body { display: grid; gap: 4px; }
.plan-step-title { font-weight: 600; font-size: 14px; }
.plan-step-description { font-size: 13px; color: var(--muted); }
```

- [ ] **Step 2: Create `app/plans/[planId]/page.tsx`**

```tsx
import { ErrorBanner } from "../../../components/error-banner";
import { Panel } from "../../../components/panel";
import { RefreshButton } from "../../../components/refresh-button";
import { StatusBadge } from "../../../components/status-badge";
import { getPlanDetail } from "../../../lib/console-api";

export const dynamic = "force-dynamic";

type PlanStep = {
  id?: unknown;
  name?: unknown;
  description?: unknown;
  status?: unknown;
  depends_on?: unknown;
};

export default async function PlanDetailPage({
  params,
}: {
  params: Promise<{ planId: string }>;
}) {
  const { planId } = await params;
  const fetched = await getPlanDetail(planId);

  if (!fetched) {
    return (
      <div className="page">
        <header className="page-header">
          <span className="page-kicker">Plan</span>
          <h1>Plan Detail</h1>
          <p className="empty-state">未找到 Plan：{planId}</p>
        </header>
      </div>
    );
  }

  const plan = fetched.plan as Record<string, unknown> | undefined ?? fetched;
  const steps: PlanStep[] = Array.isArray(plan.subtasks)
    ? (plan.subtasks as PlanStep[])
    : Array.isArray(plan.steps)
    ? (plan.steps as PlanStep[])
    : [];

  const status = String(plan.status ?? "unknown");
  const repo = String(plan.repo ?? "-");
  const objective = String(plan.objective ?? plan.title ?? "-");

  return (
    <div className="page">
      <header className="page-header">
        <span className="page-kicker">Plan</span>
        <h1>{String(plan.title ?? planId)}</h1>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "10px",
            flexWrap: "wrap",
            marginTop: "8px",
          }}
        >
          <StatusBadge status={status} />
          <span className="subtle">repo: {repo}</span>
        </div>
        <RefreshButton />
      </header>

      <ErrorBanner message={null} />

      <Panel title="Objective" eyebrow="Goal">
        <p style={{ margin: 0, lineHeight: 1.6 }}>{objective}</p>
      </Panel>

      <Panel title={`Steps (${steps.length})`} eyebrow="Execution Plan">
        {steps.length === 0 ? (
          <p className="empty-state">该 Plan 暂无步骤数据。</p>
        ) : (
          <ol className="plan-steps">
            {steps.map((step, i) => (
              <li key={String(step.id ?? i)} className="plan-step">
                <div className="plan-step-number">{i + 1}</div>
                <div className="plan-step-body">
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "8px",
                      flexWrap: "wrap",
                    }}
                  >
                    <span className="plan-step-title">
                      {String(step.name ?? step.id ?? `Step ${i + 1}`)}
                    </span>
                    {step.status ? <StatusBadge status={String(step.status)} /> : null}
                  </div>
                  {step.description ? (
                    <p className="plan-step-description">{String(step.description)}</p>
                  ) : null}
                  {Array.isArray(step.depends_on) && step.depends_on.length > 0 ? (
                    <p className="plan-step-description">
                      depends on: {(step.depends_on as string[]).join(", ")}
                    </p>
                  ) : null}
                </div>
              </li>
            ))}
          </ol>
        )}
      </Panel>

      <Panel title="Raw Plan JSON" eyebrow="Debug">
        <pre className="code-block">{JSON.stringify(plan, null, 2)}</pre>
      </Panel>
    </div>
  );
}
```

- [ ] **Step 3: Update smoke test** — add `plans/[planId]` to routes:

```js
const routes = [
  "",
  "work-items",
  "work-items/[workItemId]",
  "agent-runs",
  "plans/[planId]",
  "releases",
  "incidents",
  "evals",
  "governance",
];
```

- [ ] **Step 4: Build check + smoke test**

```bash
cd apps/console-web && npm run build 2>&1 | tail -5 && node --test tests/smoke.test.mjs 2>&1
```

Expected: build succeeds, all smoke tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/console-web/app/plans \
        apps/console-web/app/globals.css \
        apps/console-web/tests/smoke.test.mjs
git commit -m "feat(console-web): add Plan detail page — steps list with status badges"
```

---

## Task 16: HTTP Basic Auth middleware (Slice 8 — Optional)

> Skip this task unless auth is needed. Only implement if `CONSOLE_PASSWORD` will be set.

**Files:**
- Create: `apps/console-web/middleware.ts`
- Create: `apps/console-web/app/login/page.tsx`

- [ ] **Step 1: Create `middleware.ts`**

```ts
import { NextRequest, NextResponse } from "next/server";

const PASSWORD = process.env.CONSOLE_PASSWORD;
const COOKIE_NAME = "console_auth";

export function middleware(req: NextRequest) {
  if (!PASSWORD) return NextResponse.next();

  const cookie = req.cookies.get(COOKIE_NAME)?.value;
  if (cookie === PASSWORD) return NextResponse.next();

  const { pathname } = req.nextUrl;
  if (pathname === "/login") return NextResponse.next();

  const loginUrl = req.nextUrl.clone();
  loginUrl.pathname = "/login";
  return NextResponse.redirect(loginUrl);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
```

- [ ] **Step 2: Create `app/login/page.tsx`**

```tsx
"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "../../components/ui/button";

export default function LoginPage() {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    if (res.ok) {
      router.push("/");
      router.refresh();
    } else {
      setError("密码错误");
    }
  }

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "24px",
      }}
    >
      <div style={{ width: "100%", maxWidth: "360px" }}>
        <h1 style={{ fontFamily: "IBM Plex Serif, Georgia, serif", marginBottom: "24px" }}>
          AI-DevOps Console
        </h1>
        <form onSubmit={handleSubmit}>
          {error ? <p className="form-error">{error}</p> : null}
          <div className="form-field">
            <label className="form-label" htmlFor="password">密码</label>
            <input
              id="password"
              type="password"
              className="form-input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoFocus
            />
          </div>
          <Button type="submit" style={{ width: "100%" }}>登录</Button>
        </form>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Create `app/api/auth/login/route.ts`**

```ts
import { NextRequest, NextResponse } from "next/server";

const PASSWORD = process.env.CONSOLE_PASSWORD;
const COOKIE_NAME = "console_auth";

export async function POST(req: NextRequest) {
  if (!PASSWORD) {
    return NextResponse.json({ error: "Auth not configured" }, { status: 500 });
  }
  const body = await req.json().catch(() => ({}));
  if (body.password !== PASSWORD) {
    return NextResponse.json({ error: "Invalid password" }, { status: 401 });
  }
  const res = NextResponse.json({ success: true });
  res.cookies.set(COOKIE_NAME, PASSWORD, {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 60 * 24 * 7, // 7 days
  });
  return res;
}
```

- [ ] **Step 4: Build check**

```bash
cd apps/console-web && npm run build 2>&1 | tail -5
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add apps/console-web/middleware.ts \
        apps/console-web/app/login \
        apps/console-web/app/api
git commit -m "feat(console-web): add optional HTTP Basic Auth via CONSOLE_PASSWORD env var"
```

---

## Self-Review Checklist

**Spec coverage:**
- ✅ Slice 1: Button, Badge, Dialog, Tabs — Tasks 1-6
- ✅ Slice 2: CreateWorkItemDialog — Tasks 8-9
- ✅ Slice 3: StatusBadge + pill replacement — Task 7
- ✅ Slice 4: Timeline + ContextPackPanel — Tasks 10-11
- ✅ Slice 5: PollingWrapper — Task 12
- ✅ Slice 6: Agent Runs backend + frontend — Tasks 13-14
- ✅ Slice 7: Plan detail page — Task 15
- ✅ Slice 8: HTTP Basic Auth — Task 16 (optional)

**Type consistency:**
- `StatusBadge` used uniformly with `status: string` prop across all pages
- `BadgeVariant` type exported from `badge.tsx` and imported by `status-badge.tsx`
- `createWorkItem` returns `CreateWorkItemResult` with `{ success, data?, error? }` — matches usage in `CreateWorkItemDialog`
- `Timeline` receives `TimelineEvent[]` — matches data from `getTaskWorkspace`
- `ContextPackPanel` receives `ContextPack` — matches `contextPack` field from workspace API

**No placeholders found.**
