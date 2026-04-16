import { ErrorBanner } from "../components/error-banner";
import { MetricGrid } from "../components/metric-grid";
import { Panel } from "../components/panel";
import { RefreshButton } from "../components/refresh-button";
import { TimelineList } from "../components/timeline-list";
import { getMissionControl } from "../lib/console-api";
import { missionControlMetrics, resourceErrorMessage } from "../lib/console-data.mjs";

export const dynamic = "force-dynamic";

export default async function MissionControlPage() {
  const fetched = await getMissionControl();
  const data = fetched ?? {
    workItems: { total: 0, byStatus: {} },
    releases: { total: 0, active: 0 },
    incidents: { total: 0, open: 0 },
    recentEvents: [],
  };
  const metrics = missionControlMetrics(data);
  const errorMessage = resourceErrorMessage(fetched, "Mission Control");

  return (
    <div className="page">
      <header className="page-header">
        <span className="page-kicker">Phase 6</span>
        <h1>Mission Control</h1>
        <p>统一查看当前 WorkItem、发布态、事故态和最近事件流。</p>
        <RefreshButton />
      </header>

      <ErrorBanner message={errorMessage} />

      <MetricGrid metrics={metrics} />

      <Panel title="Recent Events" eyebrow="Event Stream">
        <TimelineList
          events={(Array.isArray(data.recentEvents) ? data.recentEvents : []) as Record<string, unknown>[]}
          emptyText="当前还没有事件数据。"
        />
      </Panel>
    </div>
  );
}
