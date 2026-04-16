"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, useTransition } from "react";

import { autoRefreshLabel, autoRefreshOptions } from "../lib/console-data.mjs";

export function RefreshButton() {
  const router = useRouter();
  const [lastRefreshAt, setLastRefreshAt] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();
  const [autoEnabled, setAutoEnabled] = useState(true);
  const [intervalMs, setIntervalMs] = useState(autoRefreshOptions[0]);

  useEffect(() => {
    if (!autoEnabled) {
      return;
    }
    const timer = window.setInterval(() => {
      startTransition(() => {
        router.refresh();
        setLastRefreshAt(new Date().toLocaleTimeString("zh-CN", { hour12: false }));
      });
    }, intervalMs);
    return () => window.clearInterval(timer);
  }, [autoEnabled, intervalMs, router, startTransition]);

  return (
    <div className="refresh-wrap">
      <div className="refresh-actions">
        <button
          type="button"
          className="refresh-button"
          onClick={() =>
            startTransition(() => {
              router.refresh();
              setLastRefreshAt(new Date().toLocaleTimeString("zh-CN", { hour12: false }));
            })
          }
        >
          {isPending ? "刷新中..." : "刷新数据"}
        </button>
        <button
          type="button"
          className="refresh-toggle"
          onClick={() => setAutoEnabled((value) => !value)}
        >
          {autoRefreshLabel(autoEnabled, intervalMs)}
        </button>
        <select
          aria-label="自动刷新间隔"
          className="refresh-select"
          value={intervalMs}
          onChange={(event) => setIntervalMs(Number(event.target.value))}
        >
          {autoRefreshOptions.map((option) => (
            <option key={option} value={option}>
              {Math.round(option / 1000)} 秒
            </option>
          ))}
        </select>
      </div>
      <span className="subtle">{lastRefreshAt ? `上次刷新 ${lastRefreshAt}` : "手动刷新以获取最新状态"}</span>
    </div>
  );
}
