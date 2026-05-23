import type { Metadata } from "next";
import { Geist, Geist_Mono, Instrument_Serif } from "next/font/google";
import "./globals.css";
import { UI_COPY } from "@/lib/app-config";

const fontSans = Geist({
  subsets: ["latin"],
  variable: "--font-sans",
  weight: ["300", "400", "500", "600", "700"],
});

const fontMono = Geist_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  weight: ["400", "500", "600"],
});

const fontSerif = Instrument_Serif({
  subsets: ["latin"],
  variable: "--font-serif",
  style: ["normal", "italic"],
  weight: "400",
});

export const metadata: Metadata = {
  title: UI_COPY.appName,
  description: UI_COPY.appDescription
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${fontSans.variable} ${fontMono.variable} ${fontSerif.variable}`}>
      <body>{children}</body>
    </html>
  );
}
