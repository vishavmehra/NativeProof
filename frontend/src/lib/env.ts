/** Public runtime configuration. Only NEXT_PUBLIC_* values belong here, never secrets. */
export const env = {
  apiBaseUrl: process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000",
  authMode: (process.env.NEXT_PUBLIC_AUTH_MODE === "supabase" ? "supabase" : "dev") as "supabase" | "dev",
  supabaseUrl: process.env.NEXT_PUBLIC_SUPABASE_URL ?? "",
  supabasePublishableKey: process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY ?? "",
  // The mock transport is a development aid; it can never be enabled in a production build.
  apiMock: process.env.NEXT_PUBLIC_API_MOCK === "1" && process.env.NODE_ENV !== "production",
};
