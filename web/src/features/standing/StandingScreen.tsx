import { useCallback, useEffect, useState } from "react";
import { errorMessage, get, post } from "../../api/client";
import type { AcademicStanding, Paginated, StandingAppeal, Term } from "../../api/types";

const TIER_LABEL: Record<string, string> = {
  good: "Good standing",
  probation: "Probation",
  suspension: "Suspension",
  dismissal: "Dismissal",
};

/** Registrar-facing standing register and appeals queue (S-W04). */
export function StandingScreen({ campusCode }: { campusCode: string | null }) {
  const [tab, setTab] = useState<"register" | "appeals">("register");
  return (
    <>
      <h1>Academic standing</h1>
      <div className="filters">
        <button className={tab === "register" ? "" : "secondary"} onClick={() => setTab("register")}>
          Standing register
        </button>
        <button className={tab === "appeals" ? "" : "secondary"} onClick={() => setTab("appeals")}>
          Appeals queue
        </button>
      </div>
      {tab === "register" ? <StandingRegister campusCode={campusCode} /> : <AppealsQueue />}
    </>
  );
}

function StandingRegister({ campusCode }: { campusCode: string | null }) {
  const [rows, setRows] = useState<AcademicStanding[]>([]);
  const [terms, setTerms] = useState<Term[]>([]);
  const [tier, setTier] = useState("");
  const [overrides, setOverrides] = useState<Record<number, { term?: string; tier?: string; reason?: string }>>({});
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    const params = new URLSearchParams();
    if (campusCode) params.set("campus_code", campusCode);
    if (tier) params.set("tier", tier);
    get<Paginated<AcademicStanding>>(`/standing/students/?${params}`)
      .then((r) => {
        setRows(r.results);
        setError(null);
      })
      .catch((err) => setError(errorMessage(err, "Could not load the standing register.")));
  }, [campusCode, tier]);

  useEffect(load, [load]);
  useEffect(() => {
    get<Paginated<Term>>("/academics/terms/").then((r) => setTerms(r.results)).catch(() => setTerms([]));
  }, []);

  async function override(row: AcademicStanding) {
    const change = overrides[row.id];
    if (!change?.term || !change.tier || !change.reason?.trim()) {
      setError("Choose a term and tier, and give a reason, before overriding.");
      return;
    }
    try {
      await post(`/standing/students/${row.id}/override/`, change);
      setOverrides({ ...overrides, [row.id]: undefined } as typeof overrides);
      load();
    } catch (err) {
      setError(errorMessage(err, "Could not override the standing decision."));
    }
  }

  const currentTerm = terms.find((t) => t.is_current)?.id;

  return (
    <>
      <div className="filters">
        <select aria-label="Filter by tier" value={tier} onChange={(e) => setTier(e.target.value)}>
          <option value="">All tiers</option>
          {Object.entries(TIER_LABEL).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </div>
      {error && <p className="error">{error}</p>}
      {rows.length === 0 ? (
        <p className="muted">No students on record.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Student</th>
              <th>Programme</th>
              <th>Tier</th>
              <th className="num">GPA</th>
              <th>As of</th>
              <th>Override</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td>
                  {row.student_no} {row.student_name}
                </td>
                <td>{row.programme_code}</td>
                <td>{TIER_LABEL[row.tier] ?? row.tier}</td>
                <td className="num">{row.cumulative_gpa ?? ""}</td>
                <td>{row.as_of_term_code}</td>
                <td className="filters">
                  <select
                    aria-label={`Override term for ${row.student_no}`}
                    value={overrides[row.id]?.term ?? String(currentTerm ?? "")}
                    onChange={(e) => setOverrides({ ...overrides, [row.id]: { ...overrides[row.id], term: e.target.value } })}
                  >
                    {terms.map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.code}
                      </option>
                    ))}
                  </select>
                  <select
                    aria-label={`Override tier for ${row.student_no}`}
                    value={overrides[row.id]?.tier ?? ""}
                    onChange={(e) => setOverrides({ ...overrides, [row.id]: { ...overrides[row.id], tier: e.target.value } })}
                  >
                    <option value="">New tier…</option>
                    {Object.entries(TIER_LABEL).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                  <input
                    aria-label={`Override reason for ${row.student_no}`}
                    placeholder="Reason (required)"
                    value={overrides[row.id]?.reason ?? ""}
                    onChange={(e) => setOverrides({ ...overrides, [row.id]: { ...overrides[row.id], reason: e.target.value } })}
                  />
                  <button onClick={() => override(row)}>Override</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

function AppealsQueue() {
  const [appeals, setAppeals] = useState<StandingAppeal[]>([]);
  const [reasons, setReasons] = useState<Record<number, string>>({});
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    get<Paginated<StandingAppeal>>("/standing/appeals/?pending=1")
      .then((r) => {
        setAppeals(r.results);
        setError(null);
      })
      .catch((err) => setError(errorMessage(err, "Could not load the appeals queue.")));
  }, []);

  useEffect(load, [load]);

  async function hear(appeal: StandingAppeal, outcome: "upheld" | "denied") {
    const reason = reasons[appeal.id];
    if (!reason?.trim()) {
      setError("A reason is required to decide an appeal.");
      return;
    }
    try {
      await post(`/standing/appeals/${appeal.id}/hear/`, { outcome, reason });
      load();
    } catch (err) {
      setError(errorMessage(err, "Could not decide the appeal."));
    }
  }

  return (
    <>
      {error && <p className="error">{error}</p>}
      {appeals.length === 0 ? (
        <p className="muted">No appeals awaiting a decision.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Student</th>
              <th>Decision</th>
              <th>Grounds</th>
              <th>Decide</th>
            </tr>
          </thead>
          <tbody>
            {appeals.map((appeal) => (
              <tr key={appeal.id}>
                <td>
                  {appeal.student_no} {appeal.student_name}
                </td>
                <td>{TIER_LABEL[appeal.decision_tier] ?? appeal.decision_tier}</td>
                <td>{appeal.grounds}</td>
                <td className="filters">
                  <input
                    aria-label={`Reason for deciding ${appeal.student_no}'s appeal`}
                    placeholder="Reason (required)"
                    value={reasons[appeal.id] ?? ""}
                    onChange={(e) => setReasons({ ...reasons, [appeal.id]: e.target.value })}
                  />
                  <button onClick={() => hear(appeal, "upheld")}>Uphold</button>
                  <button className="secondary" onClick={() => hear(appeal, "denied")}>
                    Deny
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
