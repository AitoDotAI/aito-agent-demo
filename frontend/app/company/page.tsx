import AppShell from "@/components/AppShell";

// "/company/" opens the same shell on the Company AI agent tab.
export default function Company() {
  return <AppShell initialView="company" />;
}
