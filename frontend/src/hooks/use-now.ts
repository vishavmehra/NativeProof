"use client";

import { useEffect, useState } from "react";

/** Current time in ms, refreshed every `intervalMs` while `active`. Used for honest elapsed-time displays. */
export function useNow(active = true, intervalMs = 1000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [active, intervalMs]);
  return now;
}
