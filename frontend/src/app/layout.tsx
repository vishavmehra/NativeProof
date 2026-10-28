import type { Metadata } from "next";
import { Fraunces, Inter, JetBrains_Mono } from "next/font/google";

import { MockBanner } from "@/components/app-shell/mock-banner";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { env } from "@/lib/env";

import { Providers } from "./providers";
import "./globals.css";

const inter = Inter({ variable: "--font-inter", subsets: ["latin"] });
const fraunces = Fraunces({ variable: "--font-fraunces", subsets: ["latin"], axes: ["opsz", "SOFT"] });
const jetbrainsMono = JetBrains_Mono({ variable: "--font-jetbrains-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: { default: "Nativeproof", template: "%s · Nativeproof" },
  description: "Evidence-aware cultural intelligence: discover, rehearse, adapt, compare, and prove campaign decisions.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${fraunces.variable} ${jetbrainsMono.variable} h-full antialiased`}
    >
      <body className="min-h-full" data-mock={env.apiMock ? "" : undefined}>
        <Providers>
          <TooltipProvider>{children}</TooltipProvider>
          <Toaster />
        </Providers>
        <MockBanner />
      </body>
    </html>
  );
}
