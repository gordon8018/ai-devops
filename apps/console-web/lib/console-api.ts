import { buildConsoleApiUrl } from "./console-data.mjs";

const DEFAULT_BASE_URL = process.env.CONSOLE_API_BASE_URL || "http://127.0.0.1:8080";

async function fetchJson<T>(path: string): Promise<T | null> {
  try {
    const response = await fetch(buildConsoleApiUrl(DEFAULT_BASE_URL, path), {
      cache: "no-store",
    });
    if (!response.ok) {
      return null;
    }
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
