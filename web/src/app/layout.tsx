import type { Metadata } from "next";
import { Albert_Sans, Archivo, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import Providers from "./providers";

const archivo = Archivo({
  subsets: ["latin"],
  variable: "--font-display",
  display: "swap",
  weight: ["400", "500", "600", "700", "800", "900"],
});

const albertSans = Albert_Sans({
  subsets: ["latin"],
  variable: "--font-body",
  display: "swap",
  weight: ["300", "400", "500", "600", "700"],
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
  weight: ["400", "500", "600"],
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
      >
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
