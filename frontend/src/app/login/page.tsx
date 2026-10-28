import type { Metadata } from "next";
import Link from "next/link";

import { LoginPanel } from "@/components/auth/login-panel";

export const metadata: Metadata = { title: "Sign in" };

export default function LoginPage() {
  return (
    <main id="main" className="grid min-h-dvh place-items-center px-4 py-10">
      <div className="w-full max-w-sm space-y-8">
        <div className="space-y-2">
          <Link href="/" className="font-serif text-[26px] font-semibold tracking-tight text-ink">
            Nativeproof
          </Link>
          <h1 className="font-serif text-[30px] leading-tight font-medium text-ink">Sign in to your research workspace</h1>
          <p className="text-sm text-ink-secondary">Projects, evidence, and reports are private to your account.</p>
        </div>
        <div className="rounded-2xl border border-border bg-surface p-6 shadow-card">
          <LoginPanel />
        </div>
      </div>
    </main>
  );
}
