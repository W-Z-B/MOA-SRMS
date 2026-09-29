import { useEffect, useState } from "react";
import { errorMessage, get } from "../../api/client";
import type { ReportResult } from "../../api/types";

/** Enrolment and admissions at a glance, from the SRMS reports. */
export function DashboardScreen() {
  const [enrolment, setEnrolment] = useState<ReportResult | null>(null);
  const [funnel, setFunnel] = useState<ReportResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      get<ReportResult>("/reports/enrolment-by-programme/"),
      get<ReportResult>("/reports/admissions-funnel/"),
    ])
      .then(([e, f]) => {
        setEnrolment(e);
        setFunnel(f);
        setError(null);
      })
      .catch((err) => setError(errorMessage(err, "Could not load the dashboard.")));
  }, []);

  const enrolled = enrolment?.rows.reduce((sum, r) => sum + Number(r.enrolled), 0) ?? 0;
  const open =
    funnel?.rows
      .filter((r) => ["received", "screened", "offered"].includes(String(r.state)))
      .reduce((sum, r) => sum + Number(r.count), 0) ?? 0;

  return (
    <>
      <h1>Dashboard</h1>
      {error && <p className="error">{error}</p>}
      <section className="tiles">
        <div className="tile">
          <span className="num">{enrolled}</span>
          <span>Students enrolled</span>
        </div>
        <div className="tile">
          <span className="num">{enrolment?.rows.length ?? 0}</span>
          <span>Programme and campus groups</span>
        </div>
        <div className="tile">
          <span className="num">{open}</span>
          <span>Applications in progress</span>
        </div>
      </section>
      <h2>Enrolment by programme</h2>
      {!enrolment || enrolment.rows.length === 0 ? (
        <p className="muted">No students yet.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Programme</th>
              <th>Campus</th>
              <th className="num">Enrolled</th>
              <th className="num">Graduated</th>
              <th className="num">Total</th>
            </tr>
          </thead>
          <tbody>
            {enrolment.rows.map((r) => (
              <tr key={`${r.programme}-${r.campus}`}>
                <td>{r.name}</td>
                <td>{r.campus}</td>
                <td className="num">{r.enrolled}</td>
                <td className="num">{r.graduated}</td>
                <td className="num">{r.total}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
