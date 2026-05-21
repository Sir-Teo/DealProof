import type { Metadata } from "next";
import "./globals.css";
import { UI_COPY } from "@/lib/app-config";

export const metadata: Metadata = {
  title: UI_COPY.appName,
  description: UI_COPY.appDescription
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
