import { useCallback, useEffect, useState } from "react";
import { errorMessage, get, post } from "../../api/client";
import type { AcademicStanding } from "../../api/types";

const TIER_LABEL: Record<string, string> = {
  good: "Good standing",
  probation: "Probation",
  suspension: "Suspension",
  dismissal: "Dismissal",
};

/** A student's own academic standing and the right to appeal an adverse decision (S-W04). */
export function MyStandingScreen() {
  const [standing, setStanding] = useState<AcademicStanding | null>(null);
  const [grounds, setGrounds] = useState<Record<number, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(() => {
    get<AcademicStanding>("/standing/my-standing/")
      .then((s) => {
        setStanding(s);
        setError(null);
      })
      .catch((err) => setError(errorMessage(err, "Could not load your academic standing.")));
  }, []);

  useEffect(load, [load]);

  async function appeal(decisionId: number) {
    try {
      await post(`/standing/decisions/${decisionId}/appeal/`, { grounds: grounds[decisionId] ?? "" });
      setNotice("Your appeal has been lodged. You will be notified once it is heard.");
      load();
    } catch (err) {
      setError(errorMessage(err, "Could not lodge the appeal."));
    }
  }

  if (!standing) return <p className="loading">{error ?? "Loading your standing…"}</p>;

  return (
    <>
      <h1>My academic standing</h1>
      {error && <p className="error">{error}</p>}
      {notice && <p className="muted">{notice}</p>}
      <section className="tiles">
        <div className="tile">
          <span className="num">{TIER_LABEL[standing.tier] ?? standing.tier}</span>
          <span>Current standing</span>
        </div>
        <div className="tile">
          <span className="num">{standing.cumulative_gpa ?? "not available"}</span>
          <span>Cumulative GPA{standing.as_of_term_code ? ` (as of ${standing.as_of_term_code})` : ""}</span>
        </div>
      </section>
      <h2>Decision history</h2>
      {standing.decisions.length === 0 ? (
        <p className="muted">No standing decisions on record yet.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Term</th>
              <th>Change</th>
              <th className="num">GPA</th>
              <th>Reason</th>
              <th>Date</th>
              <th>Appeal</th>
            </tr>
          </thead>
          <tbody>
            {standing.decisions.map((d) => (
              <tr key={d.id}>
                <td>{d.term_code}</td>
                <td>
                  {TIER_LABEL[d.previous_tier] ?? d.previous_tier} → {TIER_LABEL[d.tier] ?? d.tier}
                </td>
                <td className="num">{d.cumulative_gpa ?? ""}</td>
                <td>{d.reason || (d.is_automatic ? "Automatic, from published results" : "")}</td>
                <td>{new Date(d.created_at).toLocaleDateString()}</td>
                <td>
                  {d.tier === "good" ? (
                    <span className="muted small">Not appealable</span>
                  ) : d.has_appeal ? (
                    <span className="pill">Appeal lodged</span>
                  ) : (
                    <div className="filters">
                      <input
                        aria-label={`Grounds for appealing the ${d.term_code} decision`}
                        placeholder="Grounds for appeal"
                        value={grounds[d.id] ?? ""}
                        onChange={(e) => setGrounds({ ...grounds, [d.id]: e.target.value })}
                      />
                      <button onClick={() => appeal(d.id)}>Appeal</button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
