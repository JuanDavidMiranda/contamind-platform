import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "ContaMind | Salud contable",
  description: "Diagnóstico conversacional y verificable de salud contable.",
  openGraph: {
    title: "ContaMind | Salud contable",
    description: "Diagnóstico conversacional y verificable de salud contable.",
    images: ["/og.png"],
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="es">
      <body>{children}</body>
    </html>
  );
}
