import { env } from "@/lib/env";

/**
 * Persistent notice while the development mock transport serves contract fixtures
 * (NEXT_PUBLIC_API_MOCK=1; disabled in production builds). Fixed to the viewport bottom so it never scrolls away.
 */
export function MockBanner() {
  if (!env.apiMock) return null;
  return (
    <div
      role="note"
      className="fixed inset-x-0 bottom-0 z-40 flex h-6 items-center justify-center gap-2 bg-ink px-3 text-[11px] text-surface"
    >
      <span className="font-semibold tracking-wide">MOCK API</span>
      <span className="truncate">— fixture responses for UI development</span>
    </div>
  );
}
