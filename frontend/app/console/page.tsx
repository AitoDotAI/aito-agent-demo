import AppShell from "@/components/AppShell";

// "/console/" opens the same shell on the telco resolution view. ?view=augment
// and ?view=handoff still deep-link to those tabs (handled in AppShell).
export default function Console() {
  return <AppShell initialView="resolve" />;
}
