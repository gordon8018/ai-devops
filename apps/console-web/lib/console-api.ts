import { buildConsoleApiUrl } from "./console-data.mjs";

const DEFAULT_BASE_URL = process.env.CONSOLE_API_BASE_URL || "http://127.0.0.1:8080";

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
    const res = await fetch(`${getApiBaseUrl()}/api/work-items`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      return { success: false, error: body.error ?? `Request failed (${res.status})` };
    }
    return { success: true, data: body.data };
  } catch (err) {
    return { success: false, error: err instanceof Error ? err.message : "Network error" };
  }
}
