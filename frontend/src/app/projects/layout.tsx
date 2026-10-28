import { AuthGate } from "@/components/auth/auth-gate";

export default function ProjectsLayout({ children }: LayoutProps<"/projects">) {
  return <AuthGate>{children}</AuthGate>;
}
