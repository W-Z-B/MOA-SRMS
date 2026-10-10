import { useEffect, useState } from "react";
import { get } from "./api/client";
import { hasAnyRole, type Me } from "./api/types";
import { Shell } from "./app/Shell";
import { STAFF_ROLES, useHashRoute } from "./app/router";
import { AdmissionsScreen } from "./features/admissions/AdmissionsScreen";
import { LoginScreen } from "./features/auth/LoginScreen";
import { DashboardScreen } from "./features/dashboard/DashboardScreen";
import { FeesScreen } from "./features/fees/FeesScreen";
import { MyBalanceScreen } from "./features/fees/MyBalanceScreen";
import { ComingSoon } from "./features/placeholder/ComingSoon";
import { MyResultsScreen } from "./features/results/MyResultsScreen";
import { ResultsScreen } from "./features/results/ResultsScreen";
import { MyStandingScreen } from "./features/standing/MyStandingScreen";
import { StandingScreen } from "./features/standing/StandingScreen";
import { StudentsScreen } from "./features/students/StudentsScreen";

const CAMPUS_KEY = "gsa-srms.campus";

function readCampus(): string | null {
  try {
    return localStorage.getItem(CAMPUS_KEY);
  } catch {
    return null;
  }
}

export default function App() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const [path, navigate] = useHashRoute();
  const [campusCode, setCampusCode] = useState<string | null>(readCampus);

  useEffect(() => {
    get<Me>("/auth/me/")
      .then(setMe)
      .catch(() => setMe(null));
  }, []);

  function changeCampus(code: string | null) {
    setCampusCode(code);
    try {
      if (code) localStorage.setItem(CAMPUS_KEY, code);
      else localStorage.removeItem(CAMPUS_KEY);
    } catch {
      /* per-viewer convenience only */
    }
  }

  if (me === undefined) return <p className="loading">Loading GSA SRMS…</p>;
  if (me === null || (me.mfa_required && !me.mfa_verified)) return <LoginScreen onSignedIn={setMe} />;

  const isStaff = hasAnyRole(me, STAFF_ROLES);
  const idIn = (prefix: string) => {
    const m = path.match(new RegExp(`^${prefix}/(\\d+)`));
    return m ? Number(m[1]) : null;
  };

  let screen;
  if (path === "/") screen = isStaff ? <DashboardScreen /> : <MyResultsScreen />;
  else if (path.startsWith("/students"))
    screen = <StudentsScreen me={me} campusCode={campusCode} initialId={idIn("/students")} onNavigate={navigate} />;
  else if (path.startsWith("/admissions")) screen = <AdmissionsScreen me={me} campusCode={campusCode} />;
  else if (path.startsWith("/results")) screen = <ResultsScreen me={me} campusCode={campusCode} />;
  else if (path.startsWith("/standing")) screen = <StandingScreen campusCode={campusCode} />;
  else if (path.startsWith("/fees")) screen = <FeesScreen />;
  else if (path.startsWith("/my-balance")) screen = <MyBalanceScreen />;
  else if (path.startsWith("/my-results")) screen = <MyResultsScreen />;
  else if (path.startsWith("/my-standing")) screen = <MyStandingScreen />;
  else if (path.startsWith("/admin"))
    screen = <ComingSoon title="Admin" sprint="a later sprint" requirement="programmes, calendar, grading scale" />;
  else screen = <ComingSoon title="Not found" sprint="a later sprint" requirement="unknown route" />;

  return (
    <Shell
      me={me}
      path={path}
      onNavigate={navigate}
      onLogout={() => setMe(null)}
      campusCode={campusCode}
      onCampusChange={changeCampus}
    >
      {screen}
    </Shell>
  );
}
