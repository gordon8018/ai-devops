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
