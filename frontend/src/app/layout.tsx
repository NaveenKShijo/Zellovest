import type { Metadata } from "next";
import { Plus_Jakarta_Sans } from "next/font/google";
import "./globals.css";
import { AppProviders } from "@/contexts/AppProviders";
import { LayoutShell } from "@/components/layout/LayoutShell";
import { ToastContainer } from "@/components/ui/ToastContainer";

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

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={plusJakarta.variable}>
      <body className={plusJakarta.className}>
        <AppProviders>
          <LayoutShell>
            {children}
          </LayoutShell>
          <ToastContainer />
        </AppProviders>
      </body>
    </html>
  );
}
