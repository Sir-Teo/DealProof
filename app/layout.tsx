import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "DealProof",
  description: "AI diligence red team for VC and PE claim verification."
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
