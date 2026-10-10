import { useEffect, useState } from "react";
import { errorMessage, get } from "../../api/client";
import type { AdvisorAssignment } from "../../api/types";

/** A student's own current and past advisors (S-M04). */
export function MyAdvisorScreen() {
  const [assignments, setAssignments] = useState<AdvisorAssignment[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    get<AdvisorAssignment[]>("/advising/my-advisor/")
      .then((rows) => {
        setAssignments(rows);
        setError(null);
      })
      .catch((err) => setError(errorMessage(err, "Could not load your advisor.")));
  }, []);

  if (assignments === null) return <p className="loading">{error ?? "Loading your advisor…"}</p>;

  const current = assignments.find((a) => a.ended_at === null);
  const past = assignments.filter((a) => a.ended_at !== null);

  return (
    <>
      <h1>My advisor</h1>
      {error && <p className="error">{error}</p>}
      {current ? (
        <section className="tiles">
          <div className="tile">
            <span className="num">{current.advisor_name ?? current.advisor_employee_no}</span>
            <span>Current advisor since {new Date(current.started_at).toLocaleDateString()}</span>
          </div>
        </section>
      ) : (
        <p className="muted">You have not yet been assigned an advisor.</p>
      )}
      {past.length > 0 && (
        <>
          <h2>Previous advisors</h2>
          <table>
            <thead>
              <tr>
                <th>Advisor</th>
                <th>From</th>
                <th>To</th>
                <th>Reason</th>
              </tr>
            </thead>
            <tbody>
              {past.map((a) => (
                <tr key={a.id}>
                  <td>{a.advisor_name ?? a.advisor_employee_no}</td>
                  <td>{new Date(a.started_at).toLocaleDateString()}</td>
                  <td>{a.ended_at ? new Date(a.ended_at).toLocaleDateString() : ""}</td>
                  <td>{a.ended_reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </>
  );
}
