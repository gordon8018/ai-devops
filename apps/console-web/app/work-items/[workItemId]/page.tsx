import Link from "next/link";
import { ContextPackPanel } from "../../../components/context-pack-panel";
import { ErrorBanner } from "../../../components/error-banner";
import { Panel } from "../../../components/panel";
import { PollingWrapper } from "../../../components/polling-wrapper";
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
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "10px",
            flexWrap: "wrap",
            marginTop: "8px",
          }}
        >
          <StatusBadge status={String(workItem.status ?? "unknown")} />
          <span className="subtle">repo: {String(workItem.repo ?? "-")}</span>
          {planId ? (
            <Link href={`/plans/${encodeURIComponent(planId)}`} className="inline-link">
              {planId.length > 20 ? `→ Plan ${planId.slice(0, 20)}…` : `→ Plan ${planId}`}
            </Link>
          ) : null}
        </div>
        <RefreshButton />
        <PollingWrapper status={String(workItem.status ?? "")} />
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
            <Timeline events={eventTimeline} emptyText="当前还没有时间线事件。" />
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
