import AppShell from "@/components/AppShell";

// The whole demo is one app shell; "/" opens on the Overview tab. Every
// surface (telco support views + the sales assistant) is reachable from the
// left menu — see frontend/components/AppShell.tsx.
export default function Home() {
  return <AppShell initialView="home" />;
}
