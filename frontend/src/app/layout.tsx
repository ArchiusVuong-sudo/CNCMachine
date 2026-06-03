import type { Metadata } from "next";
import { DM_Sans, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { Toaster } from "@/components/ui/sonner";
import { AnalysisStreamProvider } from "@/lib/hooks/analysis-stream-context";

const dmSans = DM_Sans({
  subsets: ["latin"],
  variable: "--font-dm-sans",
  weight: ["400", "500", "600", "700"],
});

const jetbrains = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains",
  weight: ["400", "500"],
});

export const metadata: Metadata = {
  title: "CoFab · CNC Costing Studio",
  description: "AI-powered CNC part costing — drawing + 3D model in, per-component cost out.",
  icons: {
    icon: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className={`${dmSans.variable} ${jetbrains.variable} min-h-screen bg-background text-foreground antialiased`}>
        <AnalysisStreamProvider>
          {children}
        </AnalysisStreamProvider>
        <Toaster position="bottom-right" richColors closeButton />
      </body>
    </html>
  );
}
