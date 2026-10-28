"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { ErrorState, LoadingState } from "@/components/states";
import { getSupabase, supabaseConfigured } from "@/lib/auth/supabase";
import { env } from "@/lib/env";

/**
 * Route guard. Dev auth mode needs no sign-in (token.ts sends the development token).
 * Supabase mode renders children only with a session and redirects to /login otherwise.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  if (env.authMode === "dev") return children;
  if (!supabaseConfigured) {
    return (
      <div className="mx-auto max-w-xl p-6">
        <ErrorState error={new Error("Supabase auth mode is enabled, but NEXT_PUBLIC_SUPABASE_URL or NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY is missing.")} />
      </div>
    );
  }
  return <SupabaseGate>{children}</SupabaseGate>;
}

function SupabaseGate({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [signedIn, setSignedIn] = useState<boolean | null>(null);

  useEffect(() => {
    const supabase = getSupabase();
    let cancelled = false;
    supabase.auth.getSession().then(({ data }) => {
      if (cancelled) return;
      setSignedIn(Boolean(data.session));
      if (!data.session) router.replace("/login");
    });
    const { data } = supabase.auth.onAuthStateChange((_event, session) => {
      setSignedIn(Boolean(session));
      if (!session) router.replace("/login");
    });
    return () => {
      cancelled = true;
      data.subscription.unsubscribe();
    };
  }, [router]);

  if (!signedIn) return <LoadingState label={signedIn === null ? "Checking your session…" : "Redirecting to sign in…"} />;
  return children;
}
