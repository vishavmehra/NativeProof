"use client";

import { createBrowserClient } from "@supabase/ssr";
import type { SupabaseClient } from "@supabase/supabase-js";

import { setTokenProvider } from "@/lib/auth/token";
import { env } from "@/lib/env";

export const supabaseConfigured = Boolean(env.supabaseUrl && env.supabasePublishableKey);

let client: SupabaseClient | null = null;

/**
 * Browser Supabase client for NEXT_PUBLIC_AUTH_MODE=supabase. On first use it registers the API
 * token provider, so every request carries the current session's access token.
 */
export function getSupabase(): SupabaseClient {
  if (!client) {
    if (!supabaseConfigured) {
      throw new Error("Supabase is not configured: set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY.");
    }
    const supabase = createBrowserClient(env.supabaseUrl, env.supabasePublishableKey);
    setTokenProvider(async () => (await supabase.auth.getSession()).data.session?.access_token ?? null);
    client = supabase;
  }
  return client;
}
