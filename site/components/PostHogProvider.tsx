// aethercloud/posthog/components/PostHogProvider.tsx
//
// Wraps your Next.js app so PostHog initializes once on the client and
// auto-fires $pageview on every route change.
//
// Next.js App Router: import into app/layout.tsx and wrap <body> children.
// Next.js Pages Router: wrap <Component> inside pages/_app.tsx.

"use client";

import { useEffect } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { initPostHog, posthog } from "../lib/posthog";

export function PostHogProvider({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const searchParams = useSearchParams();

  useEffect(() => { initPostHog(); }, []);

  useEffect(() => {
    if (!pathname) return;
    const url = searchParams?.toString()
      ? `${pathname}?${searchParams.toString()}`
      : pathname;
    posthog.capture("$pageview", { $current_url: url });
  }, [pathname, searchParams]);

  return <>{children}</>;
}
