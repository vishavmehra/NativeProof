"use client";

import { FlaskConical } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { Field } from "@/components/forms/fields";
import { ErrorState } from "@/components/states";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useCreateDemoProject } from "@/features/project/projects-dashboard";
import { getSupabase, supabaseConfigured } from "@/lib/auth/supabase";
import { env } from "@/lib/env";
import { cn } from "@/lib/utils";

/** Sign in, create an account, or try the demo through an anonymous Supabase session (contracts/README §4). */
export function LoginPanel() {
  if (env.authMode === "dev") {
    return (
      <div className="space-y-4">
        <p className="text-sm text-ink-body">Development mode is on: requests use the local development token, so there is nothing to sign in to.</p>
        <Link href="/projects" className={buttonVariants()}>
          Go to projects
        </Link>
      </div>
    );
  }
  if (!supabaseConfigured) {
    return <ErrorState error={new Error("Supabase auth mode is enabled, but NEXT_PUBLIC_SUPABASE_URL or NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY is missing.")} />;
  }
  return <SupabaseLogin />;
}

/** Google's multi-color "G" mark, as its sign-in branding guidelines require for the button. */
function GoogleMark() {
  return (
    <svg aria-hidden viewBox="0 0 48 48" className="size-4">
      <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
      <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" />
      <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
    </svg>
  );
}

function SupabaseLogin() {
  const router = useRouter();
  const demo = useCreateDemoProject();
  const [mode, setMode] = useState<"sign-in" | "sign-up">("sign-in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState<"form" | "demo" | "google" | null>(null);
  const [message, setMessage] = useState<{ tone: "error" | "info"; text: string } | null>(null);
  const [demoError, setDemoError] = useState<string | null>(null);

  // Already signed in: go straight to the projects.
  useEffect(() => {
    void getSupabase()
      .auth.getSession()
      .then(({ data }) => data.session && router.replace("/projects"));
  }, [router]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setPending("form");
    setMessage(null);
    const auth = getSupabase().auth;
    const { data, error } =
      mode === "sign-in" ? await auth.signInWithPassword({ email, password }) : await auth.signUp({ email, password });
    setPending(null);
    if (error) return setMessage({ tone: "error", text: error.message });
    if (data.session) return router.replace("/projects");
    setMessage({ tone: "info", text: "Check your email to confirm your account, then sign in." });
  }

  async function signInWithGoogle() {
    setPending("google");
    setMessage(null);
    // PKCE: Supabase sends the browser to Google, then back to /auth/callback, which finishes the session exchange.
    const { error } = await getSupabase().auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: `${window.location.origin}/auth/callback` },
    });
    if (error) {
      setPending(null);
      setMessage({ tone: "error", text: `Google sign-in could not start: ${error.message}` });
    }
  }

  async function tryDemo() {
    setPending("demo");
    setMessage(null);
    setDemoError(null);
    const { error } = await getSupabase().auth.signInAnonymously();
    if (error) {
      setPending(null);
      // Supabase rate-limits anonymous sign-ins per network; say so in plain words instead of provider text.
      const limited = error.status === 429 || /rate limit/i.test(error.message);
      return setDemoError(
        limited ? "Too many demo sessions from this network. Try again in a few minutes." : "Could not start a demo session. Try again in a moment.",
      );
    }
    demo.mutate(undefined, { onSettled: () => setPending(null) });
  }

  return (
    <div className="space-y-6">
      <div role="group" aria-label="Account action" className="inline-flex rounded-lg border border-border bg-surface-muted p-0.5">
        {(["sign-in", "sign-up"] as const).map((m) => (
          <button
            key={m}
            type="button"
            aria-pressed={mode === m}
            onClick={() => setMode(m)}
            className={cn(
              "rounded-md px-3 py-1.5 text-[13px] text-ink-secondary outline-none",
              mode === m && "bg-surface font-medium text-ink shadow-card",
            )}
          >
            {m === "sign-in" ? "Sign in" : "Create account"}
          </button>
        ))}
      </div>
      <Button variant="outline" size="lg" className="w-full" onClick={() => void signInWithGoogle()} disabled={pending !== null}>
        <GoogleMark />
        {pending === "google" ? "Opening Google…" : "Continue with Google"}
      </Button>
      <form onSubmit={submit} className="space-y-4">
        <Field label="Email" htmlFor="email" required>
          <Input id="email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required className="bg-surface" />
        </Field>
        <Field label="Password" htmlFor="password" required hint={mode === "sign-up" ? "At least 6 characters." : undefined}>
          <Input
            id="password"
            type="password"
            autoComplete={mode === "sign-in" ? "current-password" : "new-password"}
            minLength={6}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            className="bg-surface"
          />
        </Field>
        {message && (
          <p role={message.tone === "error" ? "alert" : "status"} className={cn("rounded-lg px-3 py-2 text-[13px]", message.tone === "error" ? "bg-danger-soft text-danger" : "bg-info-soft text-info")}>
            {message.text}
          </p>
        )}
        <Button type="submit" className="w-full" size="lg" disabled={pending !== null}>
          {pending === "form" ? "Working…" : mode === "sign-in" ? "Sign in" : "Create account"}
        </Button>
      </form>
      <div className="flex items-center gap-3 text-xs text-ink-secondary">
        <span className="h-px flex-1 bg-border" />
        or
        <span className="h-px flex-1 bg-border" />
      </div>
      <div className="space-y-2">
        <Button variant="outline" size="lg" className="w-full" onClick={() => void tryDemo()} disabled={pending !== null}>
          <FlaskConical aria-hidden />
          {pending === "demo" ? "Starting demo…" : "Try the demo"}
        </Button>
        <p className="text-xs text-ink-secondary">
          Starts an anonymous session and creates a project seeded with labeled fixture data (Northstar, Japan). No external provider is called.
        </p>
        {demoError && (
          <p role="alert" className="rounded-lg bg-danger-soft px-3 py-2 text-[13px] text-danger">
            {demoError}
          </p>
        )}
        {demo.error && <ErrorState error={demo.error} onRetry={() => demo.mutate()} />}
      </div>
    </div>
  );
}
