/** Hash-based routing with no dependency, shared across the GSA ecosystem front-ends. */

import { useEffect, useState } from "react";

const read = () => window.location.hash.replace(/^#/, "") || "/";

export function useHashRoute(): [string, (to: string) => void] {
  const [path, setPath] = useState<string>(read);
  useEffect(() => {
    const onChange = () => setPath(read());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return [path, (to: string) => (window.location.hash = to)];
}

export interface NavItem {
  path: string;
  label: string;
  roles?: string[];
}

const RECORDS = ["registrar", "admissions_officer", "administrator"];
const ACADEMIC = ["registrar", "hod", "lecturer", "principal", "auditor", "administrator"];
const STANDING_STAFF = ["registrar", "principal", "auditor", "administrator"];

export const NAV: NavItem[] = [
  { path: "/", label: "Dashboard", roles: [...RECORDS, ...ACADEMIC, "finance"] },
  { path: "/students", label: "Students", roles: [...RECORDS, ...ACADEMIC, "finance"] },
  { path: "/admissions", label: "Admissions", roles: [...RECORDS, "principal", "auditor"] },
  { path: "/results", label: "Results", roles: ACADEMIC },
  { path: "/standing", label: "Academic standing", roles: STANDING_STAFF },
  { path: "/fees", label: "Fees", roles: ["finance", "registrar", "administrator"] },
  { path: "/my-results", label: "My results", roles: ["student"] },
  { path: "/my-standing", label: "My standing", roles: ["student"] },
  { path: "/my-balance", label: "My balance", roles: ["student"] },
  { path: "/admin", label: "Admin", roles: ["registrar", "administrator"] },
];

export const STAFF_ROLES = [...new Set([...RECORDS, ...ACADEMIC, "finance"])];
