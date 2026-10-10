import type { Metadata } from "next";
import { Plus_Jakarta_Sans } from "next/font/google";
import "./globals.css";
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
 * All routes are session-dependent (custom AuthContext restores the local
 * JWT session from localStorage), so static prerendering is disabled.
 */
export const dynamic = "force-dynamic";

/**
 * Root layout — authentication is the custom email/password flow:
 * POST /api/v1/auth/login on the backend issues a short-lived
 * HS256 JWT; AuthContext persists it and AuthGuard gates the app shell.
 * No external identity provider (WSO2/Asgardeo) is involved.
 */
export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={plusJakarta.variable}>
      <body className={plusJakarta.className}>
        <AppProviders>
          <AuthGuard>
            <ShellGate>{children}</ShellGate>
          </AuthGuard>
          <ToastContainer />
        </AppProviders>
      </body>
    </html>
  );
}
