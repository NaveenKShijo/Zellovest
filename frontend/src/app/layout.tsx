import type { Metadata } from "next";
import localFont from "next/font/local";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";
import "./globals.css";
import { AppProviders } from "@/contexts/AppProviders";
import { ShellGate } from "@/components/layout/ShellGate";
import { ToastContainer } from "@/components/ui/ToastContainer";
import { AuthGuard } from "@/components/auth/AuthGuard";

/**
 * Plus Jakarta Sans self-hosted as a variable TTF (weights 200-800, latin).
 * next/font/local serves the file from the same origin — no Google Fonts
 * network round-trip at build/dev time, so `next dev` works offline/proxied.
 */
const plusJakarta = localFont({
  src: "./fonts/PlusJakartaSans-Variable.ttf",
  weight: "200 800",
  variable: "--font-sans",
  display: "swap",
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
