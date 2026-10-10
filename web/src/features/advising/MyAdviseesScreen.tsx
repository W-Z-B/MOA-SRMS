import { Fragment, useCallback, useEffect, useState } from "react";
import { errorMessage, get, post } from "../../api/client";
import type { Advisee } from "../../api/types";

const TIER_LABEL: Record<string, string> = {
  good: "Good standing",
  probation: "Probation",
  suspension: "Suspension",
  dismissal: "Dismissal",
};

const CONCERN_OPTIONS: { value: string; label: string }[] = [
  { value: "none", label: "No concern" },
  { value: "academic", label: "Academic concern" },
  { value: "financial", label: "Financial concern" },
  { value: "attendance", label: "Attendance concern" },
  { value: "personal", label: "Personal or welfare concern" },
];

/** An advisor's own advisees, with the same standing, hold and enrolment facts a registrar
 * already sees (S-M04) — scoped to this advisor's own employee number by the API. */
export function MyAdviseesScreen() {
  const [advisees, setAdvisees] = useState<Advisee[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);

  const load = useCallback(() => {
    get<Advisee[]>("/advising/my-advisees/")
      .then((rows) => {
        setAdvisees(rows);
        setError(null);
      })
      .catch((err) => setError(errorMessage(err, "Could not load your advisees.")));
  }, []);

  useEffect(load, [load]);

  if (advisees === null) return <p className="loading">{error ?? "Loading your advisees…"}</p>;

  return (
    <>
      <h1>My advisees</h1>
      {error && <p className="error">{error}</p>}
      {advisees.length === 0 ? (
        <p className="muted">You have no current advisees.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Student</th>
              <th>Programme</th>
              <th>Standing</th>
              <th className="num">GPA</th>
              <th>Holds</th>
              <th>Current courses</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {advisees.map((a) => (
              <Fragment key={a.id}>
                <tr>
                  <td>
                    {a.student_no} {a.full_name}
                  </td>
                  <td>{a.programme_code}</td>
                  <td>{a.standing_tier ? TIER_LABEL[a.standing_tier] ?? a.standing_tier : "Not yet computed"}</td>
                  <td className="num">{a.cumulative_gpa ?? ""}</td>
                  <td>{a.active_holds.length > 0 ? <span className="pill">{a.active_holds.join(", ")}</span> : ""}</td>
                  <td>{a.current_offerings.join(", ") || "None"}</td>
                  <td>
                    <button className="secondary" onClick={() => setExpanded(expanded === a.id ? null : a.id)}>
                      {expanded === a.id ? "Close" : "Log a note"}
                    </button>
                  </td>
                </tr>
                {expanded === a.id && (
                  <tr>
                    <td colSpan={7}>
                      <NoteForm studentId={a.id} onSaved={() => setExpanded(null)} />
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

function NoteForm({ studentId, onSaved }: { studentId: number; onSaved: () => void }) {
  const [metOn, setMetOn] = useState(new Date().toISOString().slice(0, 10));
  const [summary, setSummary] = useState("");
  const [concern, setConcern] = useState("none");
  const [flag, setFlag] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    if (!summary.trim()) {
      setError("A summary of the conversation is required.");
      return;
    }
    try {
      await post("/advising/notes/", {
        student: studentId,
        met_on: metOn,
        summary,
        concern,
        flagged_for_registrar: flag,
      });
      onSaved();
    } catch (err) {
      setError(errorMessage(err, "Could not save the advising note."));
    }
  }

  return (
    <div className="panel">
      {error && <p className="error">{error}</p>}
      <div className="filters">
        <label>
          Met on
          <input type="date" value={metOn} onChange={(e) => setMetOn(e.target.value)} />
        </label>
        <select aria-label="Concern" value={concern} onChange={(e) => setConcern(e.target.value)}>
          {CONCERN_OPTIONS.map((c) => (
            <option key={c.value} value={c.value}>
              {c.label}
            </option>
          ))}
        </select>
        <label>
          <input type="checkbox" checked={flag} onChange={(e) => setFlag(e.target.checked)} />
          Flag for the Registrar
        </label>
      </div>
      <textarea
        aria-label="Summary of the conversation"
        placeholder="What was discussed…"
        value={summary}
        onChange={(e) => setSummary(e.target.value)}
      />
      <button onClick={save}>Save note</button>
    </div>
  );
}
