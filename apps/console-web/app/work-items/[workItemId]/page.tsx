import { ErrorBanner } from "../../../components/error-banner";
import { Panel } from "../../../components/panel";
import { RefreshButton } from "../../../components/refresh-button";
import { TaskWorkspaceTabs } from "../../../components/task-workspace-tabs";
import { getTaskWorkspace } from "../../../lib/console-api";
import { resourceErrorMessage, workspaceEventSummary } from "../../../lib/console-data.mjs";

export const dynamic = "force-dynamic";

export default async function TaskWorkspaceDetailPage({
  params,
}: {
  params: Promise<{ workItemId: string }>;
}) {
  const { workItemId } = await params;
  const fetched = await getTaskWorkspace(workItemId);
  const workspace = fetched;

  if (!workspace) {
    return (
      <div className="page">
        <header className="page-header">
          <span className="page-kicker">Workspace</span>
          <h1>Task Workspace</h1>
          <p>未找到 {workItemId} 对应的工作区数据。</p>
        </header>
      </div>
    );
  }

  const eventTimeline = Array.isArray(workspace.eventTimeline) ? workspace.eventTimeline : [];
  const eventSummary = workspaceEventSummary(eventTimeline);
  const errorMessage = resourceErrorMessage(fetched, "Task Workspace");

  return (
    <div className="page">
      <header className="page-header">
        <span className="page-kicker">Workspace Detail</span>
        <h1>{String((workspace.workItem as Record<string, unknown>)?.title ?? workItemId)}</h1>
        <p>展示 ContextPack、Plan Request、事件时间线以及关联发布和事故。</p>
        <RefreshButton />
      </header>

      <ErrorBanner message={errorMessage} />

      <Panel title="Status Summary" eyebrow="Timeline">
        <div className="pill-row">
          {eventSummary.length > 0 ? (
            eventSummary.map((item) => (
              <span className="pill" key={item.status}>
                {item.status}: {item.count}
              </span>
            ))
          ) : (
            <p className="empty-state">当前还没有时间线事件。</p>
          )}
        </div>
      </Panel>

      <TaskWorkspaceTabs workspace={workspace as Record<string, unknown>} />
    </div>
  );
}
