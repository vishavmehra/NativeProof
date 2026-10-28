"use client";

import { useQuery } from "@tanstack/react-query";

import { projectKeys } from "@/features/project/project-context";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";

/** The caller's projects (the switcher itself lives in the sidebar project card, app-shell.tsx). */
export function useProjectList() {
  return useQuery({
    queryKey: projectKeys.list,
    queryFn: () => unwrap(api.GET("/api/v1/projects", { params: { query: { limit: 100 } } })),
  });
}
