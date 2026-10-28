import Link from "next/link";

import { buttonVariants } from "@/components/ui/button";

export default function NotFound() {
  return (
    <main id="main" className="grid min-h-dvh place-items-center px-4">
      <div className="max-w-md space-y-4 text-center">
        <p className="text-sm font-medium text-primary">404</p>
        <h1 className="font-serif text-[34px] leading-tight font-medium text-ink">This page does not exist</h1>
        <p className="text-sm text-ink-secondary">The link may be mistyped, or the project may have been archived or belong to another account.</p>
        <Link href="/projects" className={buttonVariants()}>
          Go to your projects
        </Link>
      </div>
    </main>
  );
}
