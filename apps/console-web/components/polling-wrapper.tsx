"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

interface PollingWrapperProps {
  status: string;
  intervalMs?: number;
}

export function PollingWrapper({ status, intervalMs = 15_000 }: PollingWrapperProps) {
  const router = useRouter();
  const [online, setOnline] = useState(true);
  const [tick, setTick] = useState(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const isRunning = status.toLowerCase() === "running";

  const refresh = useCallback(() => {
    if (!navigator.onLine) {
      setOnline(false);
      return;
    }
    setOnline(true);
    router.refresh();
    setTick((t) => t + 1);
  }, [router]);

  useEffect(() => {
    function handleOnline() { setOnline(true); }
    function handleOffline() { setOnline(false); }
    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);
    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, []);

  useEffect(() => {
    if (!isRunning) {
      if (intervalRef.current) clearInterval(intervalRef.current);
      return;
    }
    intervalRef.current = setInterval(refresh, intervalMs);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [isRunning, intervalMs, refresh]);

  if (!isRunning) return null;

  return (
    <div
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "6px",
        fontSize: "12px",
        color: online ? "var(--accent)" : "var(--warning)",
        fontWeight: 600,
      }}
    >
      <span
        style={{
          display: "inline-block",
          width: "8px",
          height: "8px",
          borderRadius: "50%",
          background: "currentColor",
          animation: online ? "pulse 1.5s infinite" : "none",
        }}
      />
      {online ? `自动刷新中 (${Math.round(intervalMs / 1000)}s)` : "网络断开，已停止刷新"}
      <span style={{ color: "var(--muted)", fontWeight: 400 }}>· 已刷新 {tick} 次</span>
    </div>
  );
}
