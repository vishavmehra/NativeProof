import type { ReactNode } from "react";

import { FeatureHeader } from "@/components/app-shell/feature-header";
import type { FeatureKey } from "@/features/project/features";

// FeatureHeader carries its own mb-8; -mb-8 cancels it inside the gap-8 page grids. Drop if A makes spacing caller-controlled.
export function PageHeader({
  feature,
  title,
  description,
  actions,
}: {
  feature: FeatureKey;
  title?: string;
  description: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="-mb-8">
      <FeatureHeader feature={feature} title={title} description={description} actions={actions} />
    </div>
  );
}
