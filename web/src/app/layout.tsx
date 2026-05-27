// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";
import Providers from "./providers";
import { VersionMismatchBanner } from "@/components/shared/version-mismatch-banner";

const archivo = localFont({
  src: "../../public/fonts/archivo-latin-variable.woff2",
  variable: "--font-display",
  display: "swap",
  weight: "400 900",
});

const albertSans = localFont({
  src: "../../public/fonts/albert-sans-latin-variable.woff2",
  variable: "--font-body",
  display: "swap",
  weight: "300 700",
});

const jetbrainsMono = localFont({
  src: "../../public/fonts/jetbrains-mono-latin-variable.woff2",
  variable: "--font-mono",
  display: "swap",
  weight: "400 600",
});

export const metadata: Metadata = {
  title: "Observal",
  description: "Agent registry with built-in observability",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body
        className={`${archivo.variable} ${albertSans.variable} ${jetbrainsMono.variable} min-h-svh antialiased`}
        suppressHydrationWarning
      >
        <Providers>
          {children}
          <VersionMismatchBanner />
        </Providers>
      </body>
    </html>
  );
}
