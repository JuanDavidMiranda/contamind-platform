import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "ContaMind | Agentes contables",
  description: "Diagnósticos verificables de salud contable y cartera.",
  openGraph: {
    title: "ContaMind | Agentes contables",
    description: "Diagnósticos verificables de salud contable y cartera.",
    images: ["/og-agentes.png"],
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="es">
      <body>{children}</body>
    </html>
  );
}
