"use client";

import { createContext, type ReactNode, useContext, useState } from "react";
import { cn } from "../../lib/cn";

interface TabsContextValue {
  active: string;
  setActive: (v: string) => void;
}

const TabsContext = createContext<TabsContextValue | null>(null);

function useTabsContext(): TabsContextValue {
  const ctx = useContext(TabsContext);
  if (!ctx) throw new Error("TabsTrigger/TabsContent must be used inside <Tabs>");
  return ctx;
}

export function Tabs({
  defaultValue,
  children,
  className,
}: {
  defaultValue: string;
  children: ReactNode;
  className?: string;
}) {
  const [active, setActive] = useState(defaultValue);
  return (
    <TabsContext.Provider value={{ active, setActive }}>
      <div className={cn("tabs", className)}>{children}</div>
    </TabsContext.Provider>
  );
}

export function TabsList({ children }: { children: ReactNode }) {
  return <div role="tablist" className="tabs-list">{children}</div>;
}

export function TabsTrigger({ value, children }: { value: string; children: ReactNode }) {
  const { active, setActive } = useTabsContext();
  return (
    <button
      id={`tab-${value}`}
      type="button"
      role="tab"
      className="tabs-trigger"
      aria-selected={active === value}
      aria-controls={`panel-${value}`}
      onClick={() => setActive(value)}
    >
      {children}
    </button>
  );
}

export function TabsContent({ value, children }: { value: string; children: ReactNode }) {
  const { active } = useTabsContext();
  const isActive = active === value;
  return (
    <div
      id={`panel-${value}`}
      role="tabpanel"
      aria-labelledby={`tab-${value}`}
      tabIndex={isActive ? 0 : -1}
      hidden={!isActive}
      className="tabs-content"
      data-active={isActive ? "true" : "false"}
    >
      {children}
    </div>
  );
}
