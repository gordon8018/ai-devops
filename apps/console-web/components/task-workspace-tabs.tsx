"use client";

import { useState } from "react";

import { MetricGrid } from "./metric-grid";
import { Panel } from "./panel";
import { TimelineList } from "./timeline-list";
import { workspaceOverviewCards, workspaceViewItems } from "../lib/console-data.mjs";

type WorkspaceRecord = Record<string, unknown>;

export function TaskWorkspaceTabs({ workspace }: { workspace: WorkspaceRecord }) {
  const [activeView, setActiveView] = useState("summary");
  const tabs = workspaceViewItems();
  const overview = workspaceOverviewCards(workspace);
  const eventTimeline = (Array.isArray(workspace.eventTimeline) ? workspace.eventTimeline : []) as WorkspaceRecord[];

  return (
    <div className="page">
      <div className="tab-row">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={tab.id === activeView ? "tab-button active" : "tab-button"}
            onClick={() => setActiveView(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeView === "summary" ? (
        <>
          <MetricGrid metrics={overview} />
          <Panel title="Context Snapshot" eyebrow="Summary">
            <div className="stack">
              <p className="subtle">
                Work Item: {String((workspace.workItem as WorkspaceRecord)?.workItemId ?? "-")}
              </p>
              <p className="subtle">
                Context Pack: {String((workspace.contextPack as WorkspaceRecord)?.packId ?? "-")}
              </p>
              <p className="subtle">
                Plan ID: {String((workspace.planRequest as WorkspaceRecord)?.planId ?? "-")}
              </p>
            </div>
          </Panel>
          <Panel title="Linked Release" eyebrow="Release">
            <pre className="code-block">{JSON.stringify(workspace.release ?? {}, null, 2)}</pre>
          </Panel>
          <Panel title="Linked Incidents" eyebrow="Incident">
            <pre className="code-block">{JSON.stringify(workspace.incidents ?? [], null, 2)}</pre>
          </Panel>
        </>
      ) : null}

      {activeView === "raw" ? (
        <Panel title="Raw Workspace JSON" eyebrow="JSON">
          <pre className="code-block">{JSON.stringify(workspace, null, 2)}</pre>
        </Panel>
      ) : null}

      {activeView === "timeline" ? (
        <Panel title="Event Timeline" eyebrow="Events">
          <TimelineList events={eventTimeline} emptyText="当前还没有时间线事件。" />
        </Panel>
      ) : null}
    </div>
  );
}
