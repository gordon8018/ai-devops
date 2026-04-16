export function buildConsoleApiUrl(baseUrl, path) {
  const trimmedBase = String(baseUrl || "").replace(/\/+$/, "");
  const trimmedPath = String(path || "").replace(/^\/+/, "");
  return `${trimmedBase}/${trimmedPath}`;
}

export function missionControlMetrics(summary) {
  return [
    { label: "Work Items", value: String(summary?.workItems?.total ?? 0) },
    { label: "Active Releases", value: String(summary?.releases?.active ?? 0) },
    { label: "Open Incidents", value: String(summary?.incidents?.open ?? 0) },
    { label: "Recent Events", value: String(summary?.recentEvents?.length ?? 0) },
  ];
}

export function workspaceEventSummary(events) {
  const counts = new Map();
  for (const event of events || []) {
    const status = event?.data?.status;
    if (!status) continue;
    counts.set(status, (counts.get(status) || 0) + 1);
  }
  return [...counts.entries()].map(([status, count]) => ({ status, count }));
}

export function describeTimelineEvent(event) {
  return {
    title: String(event?.type ?? "unknown"),
    status: String(event?.data?.status ?? "unknown"),
    subject: String(event?.data?.task_id ?? event?.data?.work_item_id ?? "-"),
    source: String(event?.source ?? "system"),
    details: JSON.stringify(event?.data?.details ?? {}),
  };
}

export function resourceErrorMessage(payload, label) {
  if (payload) {
    return null;
  }
  return `${label} 数据暂时不可用。`;
}

export function workspaceViewItems() {
  return [
    { id: "summary", label: "摘要" },
    { id: "raw", label: "原始 JSON" },
    { id: "timeline", label: "事件时间线" },
  ];
}

export function workspaceOverviewCards(workspace) {
  return [
    { label: "Linked Release", value: String(workspace?.release ? 1 : 0) },
    { label: "Linked Incidents", value: String((workspace?.incidents || []).length) },
    { label: "Timeline Events", value: String((workspace?.eventTimeline || []).length) },
  ];
}

export const autoRefreshOptions = [15000, 30000, 60000];

export function autoRefreshLabel(enabled, intervalMs) {
  if (!enabled) {
    return "自动刷新已暂停";
  }
  return `自动刷新 ${Math.round(intervalMs / 1000)}s`;
}

export function evalGovernanceCards(governance) {
  return [
    { label: "Legacy Entrypoints", value: String(governance?.legacyEntrypoints?.total ?? 0) },
    { label: "Legacy Work Items", value: String(governance?.workItemSources?.legacy_task_input ?? 0) },
    { label: "Platform Work Items", value: String(governance?.workItemSources?.platform ?? 0) },
    { label: "Cutover Ready", value: governance?.cutoverReadiness?.ready ? "Yes" : "No" },
  ];
}
