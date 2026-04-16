import test from "node:test";
import assert from "node:assert/strict";

import {
  autoRefreshLabel,
  autoRefreshOptions,
  buildConsoleApiUrl,
  describeTimelineEvent,
  evalGovernanceCards,
  resourceErrorMessage,
  missionControlMetrics,
  workspaceOverviewCards,
  workspaceViewItems,
  workspaceEventSummary,
} from "../lib/console-data.mjs";

test("buildConsoleApiUrl joins base url and route safely", () => {
  assert.equal(
    buildConsoleApiUrl("http://localhost:8080/", "/api/console/mission-control"),
    "http://localhost:8080/api/console/mission-control",
  );
});

test("missionControlMetrics maps aggregate payload into dashboard cards", () => {
  const metrics = missionControlMetrics({
    workItems: { total: 3 },
    releases: { active: 2 },
    incidents: { open: 1 },
    recentEvents: [{ type: "task_status" }, { type: "alert" }],
  });

  assert.deepEqual(metrics, [
    { label: "Work Items", value: "3" },
    { label: "Active Releases", value: "2" },
    { label: "Open Incidents", value: "1" },
    { label: "Recent Events", value: "2" },
  ]);
});

test("workspaceEventSummary groups timeline events by status", () => {
  const summary = workspaceEventSummary([
    { data: { status: "running" } },
    { data: { status: "running" } },
    { data: { status: "ready" } },
  ]);

  assert.deepEqual(summary, [
    { status: "running", count: 2 },
    { status: "ready", count: 1 },
  ]);
});

test("describeTimelineEvent maps event payload into readable summary", () => {
  const summary = describeTimelineEvent({
    type: "task_status",
    source: "monitor",
    data: {
      task_id: "wi_001",
      status: "running",
      details: { step: "planning" },
    },
  });

  assert.deepEqual(summary, {
    title: "task_status",
    status: "running",
    subject: "wi_001",
    source: "monitor",
    details: '{"step":"planning"}',
  });
});

test("resourceErrorMessage returns fallback for missing payload", () => {
  assert.equal(resourceErrorMessage(null, "Mission Control"), "Mission Control 数据暂时不可用。");
  assert.equal(resourceErrorMessage({ workItems: { total: 1 } }, "Mission Control"), null);
});

test("workspaceViewItems exposes summary raw timeline tabs", () => {
  assert.deepEqual(
    workspaceViewItems().map((item) => item.id),
    ["summary", "raw", "timeline"],
  );
});

test("workspaceOverviewCards summarizes linked resources", () => {
  const cards = workspaceOverviewCards({
    release: { releaseId: "rel_001" },
    incidents: [{ incidentId: "inc_001" }, { incidentId: "inc_002" }],
    eventTimeline: [{ data: { status: "running" } }, { data: { status: "ready" } }],
  });

  assert.deepEqual(cards, [
    { label: "Linked Release", value: "1" },
    { label: "Linked Incidents", value: "2" },
    { label: "Timeline Events", value: "2" },
  ]);
});

test("autoRefresh helpers expose default options and labels", () => {
  assert.deepEqual(autoRefreshOptions, [15000, 30000, 60000]);
  assert.equal(autoRefreshLabel(true, 15000), "自动刷新 15s");
  assert.equal(autoRefreshLabel(false, 15000), "自动刷新已暂停");
});

test("evalGovernanceCards summarizes legacy cutover signals", () => {
  const cards = evalGovernanceCards({
    legacyEntrypoints: {
      total: 2,
      byEntrypoint: { "zoe_tools.build_work_item_session": 2 },
    },
    workItemSources: { legacy_task_input: 3, platform: 1 },
    cutoverReadiness: {
      ready: false,
      blockingReasons: ["legacy_entrypoints_active", "legacy_work_items_present"],
    },
  });

  assert.deepEqual(cards, [
    { label: "Legacy Entrypoints", value: "2" },
    { label: "Legacy Work Items", value: "3" },
    { label: "Platform Work Items", value: "1" },
    { label: "Cutover Ready", value: "No" },
  ]);
});
