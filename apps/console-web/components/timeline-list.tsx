import { describeTimelineEvent } from "../lib/console-data.mjs";

export function TimelineList({
  events,
  emptyText,
}: {
  events: Record<string, unknown>[];
  emptyText: string;
}) {
  if (events.length === 0) {
    return <p className="empty-state">{emptyText}</p>;
  }

  return (
    <div className="stack">
      {events.map((event, index) => {
        const item = describeTimelineEvent(event);
        return (
          <div className="timeline-item" key={`${item.title}-${item.subject}-${index}`}>
            <div className="timeline-row">
              <strong>{item.title}</strong>
              <span className="pill">{item.status}</span>
            </div>
            <p className="subtle">
              {item.subject} · {item.source}
            </p>
            <code className="timeline-detail">{item.details}</code>
          </div>
        );
      })}
    </div>
  );
}
