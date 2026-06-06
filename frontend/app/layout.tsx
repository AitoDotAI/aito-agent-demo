import type { Metadata } from "next";
import "./globals.css";
import Analytics from "@/components/shell/Analytics";

export const metadata: Metadata = {
  metadataBase: new URL("https://agent.aito.ai"),
  title: "Predictive Agent — Aito in your agent's toolbox",
  description:
    "A live agent that calls Aito ops as tools: win-odds, effort, references and the outreach that books the most meetings — grounded numbers an LLM can't invent. Reasoning, memory, and now intuition.",
  icons: { icon: "/aito-favicon.svg" },
  openGraph: {
    title: "Predictive Agent — Aito in your agent's toolbox",
    description:
      "LLMs reason. RAG remembers. Aito knows. A live gpt-5-mini agent grounded by Aito _predict / _estimate / _recommend — better, faster, cheaper, and higher-yield.",
    url: "https://agent.aito.ai",
    siteName: "Aito",
    images: [{ url: "/teaser.png", width: 1200, height: 630, alt: "Predictive Agent — Aito in your agent's toolbox" }],
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "Predictive Agent — Aito in your agent's toolbox",
    description: "A live agent grounded by Aito ops — win-odds, effort, references, and the outreach that wins.",
    images: ["/teaser.png"],
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Analytics />
        {children}
      </body>
    </html>
  );
}
