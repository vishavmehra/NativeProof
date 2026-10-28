"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { buttonVariants } from "@/components/ui/button";
import { getSupabase } from "@/lib/auth/supabase";

/** OAuth return page. The Supabase browser client exchanges the PKCE code from the URL while it initializes;
 * getSession() resolves after that exchange, so a session here means sign-in completed. */
export default function AuthCallbackPage() {
  const router = useRouter();
  const [failure, setFailure] = useState<string | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const providerError = params.get("error_description") ?? params.get("error");
    void getSupabase()
      .auth.getSession()
      .then(({ data, error }) => {
        if (data.session) return router.replace("/projects");
        setFailure(providerError ?? error?.message ?? "Sign-in did not complete. Try again.");
      });
  }, [router]);

  return (
    <main id="main" className="mx-auto flex min-h-dvh max-w-md flex-col justify-center gap-4 px-4">
      {failure ? (
        <>
          <h1 className="font-serif text-3xl text-ink">Sign-in did not complete</h1>
          <p role="alert" className="text-sm text-ink-body">
            {failure}
          </p>
          <Link href="/login" className={buttonVariants({ variant: "outline" })}>
            Back to sign in
          </Link>
        </>
      ) : (
        <p role="status" className="text-sm text-ink-secondary">
          Finishing sign-in…
        </p>
      )}
    </main>
  );
}
