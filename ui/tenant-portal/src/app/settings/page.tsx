import { redirect } from "next/navigation";

export default function LegacySettingsRedirect() {
  redirect("/select-tenant?reason=missing");
}
