import type { Metadata } from "next";
import { Plus_Jakarta_Sans } from "next/font/google";
import "./globals.css";
import { AsgardeoProvider } from "@asgardeo/nextjs/server";
import { AppProviders } from "@/contexts/AppProviders";
import { ShellGate } from "@/components/layout/ShellGate";
import { ToastContainer } from "@/components/ui/ToastContainer";
import { AuthGuard } from "@/components/auth/AuthGuard";

const plusJakarta = Plus_Jakarta_Sans({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
  weight: ["400", "500", "600", "700", "800"],
});

export const metadata: Metadata = {
  title: "Zellovest | Procurement Intelligence Platform",
  description: "AI-Native Procurement Intelligence Platform for Contract Compliance, Maverick Spend, and Vendor 360",
};

/**
 * All routes are session-dependent (AsgardeoProvider reads request headers
 * to resolve the app origin/session), so static prerendering is disabled.
 */
export const dynamic = "force-dynamic";

/**
 * Root layout — authentication is provided by the official @asgardeo/nextjs
 * SDK (Asgardeo "Big Regions" application). All credentials resolve from
 * environment variables (see .env.local / .env.example); nothing is
 * hardcoded. Scopes are exactly `openid profile` per the app spec.
 *
 * NOTE: afterSignInUrl/afterSignOutUrl are intentionally NOT set. The SDK
 * then falls back to the raw request origin (`http://localhost:3000`,
 * no trailing slash) as the OAuth redirect_uri — matching the Redirect
 * URL registered on the Asgardeo application exactly. Passing an explicit
 * URL would make the SDK normalize it to `http://localhost:3000/`
 * (trailing slash), which Asgardeo rejects as a callback-URL mismatch.
 */
export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={plusJakarta.variable}>
      <body className={plusJakarta.className}>
        <AsgardeoProvider
          baseUrl={process.env.NEXT_PUBLIC_ASGARDEO_BASE_URL}
          clientId={process.env.NEXT_PUBLIC_ASGARDEO_CLIENT_ID}
          clientSecret={process.env.ASGARDEO_CLIENT_SECRET}
          scopes={["openid", "profile"]}
        >
          <AppProviders>
            <AuthGuard>
              <ShellGate>
                {children}
              </ShellGate>
            </AuthGuard>
            <ToastContainer />
          </AppProviders>
        </AsgardeoProvider>
      </body>
    </html>
  );
}
