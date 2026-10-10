import { useEffect, useState } from "react";
import { errorMessage, get } from "../../api/client";
import type { ReportResult } from "../../api/types";
import { AttritionChart, FeeCollectionChart, FunnelChart } from "./charts";

const num = (v: string | number | null) => Number(v ?? 0);

/** Three real dashboards built from Phase A and this phase's own data: the enrolment funnel
 * (S-D01), retention and attrition by programme and cohort (S-D02), and fee collection status
 * (S-D06). Replaces the earlier placeholder. Each chart shows at most the cohorts or terms its
 * report returns by default (see `reports.api`'s DEFAULT_COHORT_YEARS / DEFAULT_TERMS_HISTORY).
 */
export function DashboardScreen() {
  const [funnel, setFunnel] = useState<ReportResult | null>(null);
  const [retention, setRetention] = useState<ReportResult | null>(null);
  const [fees, setFees] = useState<ReportResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      get<ReportResult>("/reports/enrolment-funnel/"),
      get<ReportResult>("/reports/retention-by-cohort/"),
      get<ReportResult>("/reports/fee-collection-status/"),
    ])
      .then(([f, r, c]) => {
        setFunnel(f);
        setRetention(r);
        setFees(c);
        setError(null);
      })
      .catch((err) => setError(errorMessage(err, "Could not load the dashboard.")));
  }, []);

  if (error) return <p className="error">{error}</p>;
  if (!funnel || !retention || !fees) return <p className="loading">Loading the dashboard…</p>;

  const totals = { applied: 0, admitted: 0, enrolled: 0, retained: 0, graduated: 0 };
  for (const r of funnel.rows) {
    totals.applied += num(r.applied);
    totals.admitted += num(r.admitted);
    totals.enrolled += num(r.enrolled);
    totals.retained += num(r.retained);
    totals.graduated += num(r.graduated);
  }
  const stages = [
    { label: "Applied", value: totals.applied },
    { label: "Admitted", value: totals.admitted },
    { label: "Enrolled", value: totals.enrolled },
    { label: "Retained", value: totals.retained },
    { label: "Graduated", value: totals.graduated },
  ];

  const cohortGroups = retention.rows
    .slice(0, 8)
    .map((r) => ({
      label: `${r.programme} ${r.intake_year}`,
      retained: num(r.retained),
      lost: num(r.withdrawn) + num(r.dismissed),
    }));
  const attritionTotals = retention.rows.reduce<{ total: number; lost: number }>(
    (acc, r) => ({ total: acc.total + num(r.total), lost: acc.lost + num(r.withdrawn) + num(r.dismissed) }),
    { total: 0, lost: 0 },
  );
  const overallAttrition = attritionTotals.total ? (100 * attritionTotals.lost) / attritionTotals.total : null;

  const feeRows = fees.rows.filter((r) => r.term !== "unallocated");
  const unallocated = fees.rows.find((r) => r.term === "unallocated");
  const feeGroups = feeRows.map((r) => ({ label: String(r.term), charged: num(r.charged), collected: num(r.collected) }));
  const feeTotals = feeRows.reduce<{ charged: number; collected: number }>(
    (acc, r) => ({ charged: acc.charged + num(r.charged), collected: acc.collected + num(r.collected) }),
    { charged: 0, collected: 0 },
  );
  const overallCollectionRate = feeTotals.charged ? (100 * feeTotals.collected) / feeTotals.charged : null;

  return (
    <>
      <h1>Dashboard</h1>

      <section className="module">
        <h3>Enrolment funnel (S-D01)</h3>
        <div className="tiles">
          <div className="tile">
            <span className="num">{totals.applied}</span>
            <span>Applied</span>
          </div>
          <div className="tile">
            <span className="num">{totals.graduated}</span>
            <span>Graduated</span>
          </div>
          <div className="tile">
            <span className="num">
              {totals.applied ? `${Math.round((1000 * totals.graduated) / totals.applied) / 10}%` : "—"}
            </span>
            <span>Applied-to-graduated conversion</span>
          </div>
        </div>
        <FunnelChart stages={stages} />
        <details>
          <summary>By programme and intake year</summary>
          <table>
            <thead>
              <tr>
                <th>Programme</th>
                <th className="num">Year</th>
                <th className="num">Applied</th>
                <th className="num">Admitted</th>
                <th className="num">Enrolled</th>
                <th className="num">Retained</th>
                <th className="num">Graduated</th>
              </tr>
            </thead>
            <tbody>
              {funnel.rows.map((r) => (
                <tr key={`${r.programme}-${r.intake_year}`}>
                  <td>{r.name}</td>
                  <td className="num">{r.intake_year}</td>
                  <td className="num">{r.applied}</td>
                  <td className="num">{r.admitted}</td>
                  <td className="num">{r.enrolled}</td>
                  <td className="num">{r.retained}</td>
                  <td className="num">{r.graduated}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      </section>

      <section className="module">
        <h3>Retention and attrition by programme and cohort (S-D02)</h3>
        <div className="tiles">
          <div className="tile">
            <span className="num">{overallAttrition !== null ? `${Math.round(overallAttrition * 10) / 10}%` : "—"}</span>
            <span>Overall attrition rate</span>
          </div>
          <div className="tile">
            <span className="num">{attritionTotals.total}</span>
            <span>Students across shown cohorts</span>
          </div>
        </div>
        {cohortGroups.length === 0 ? (
          <p className="muted">No cohorts yet.</p>
        ) : (
          <AttritionChart groups={cohortGroups} />
        )}
        <details>
          <summary>By programme and intake year</summary>
          <table>
            <thead>
              <tr>
                <th>Programme</th>
                <th className="num">Year</th>
                <th className="num">Total</th>
                <th className="num">Withdrawn</th>
                <th className="num">Dismissed</th>
                <th className="num">Attrition rate</th>
              </tr>
            </thead>
            <tbody>
              {retention.rows.map((r) => (
                <tr key={`${r.programme}-${r.intake_year}`}>
                  <td>{r.name}</td>
                  <td className="num">{r.intake_year}</td>
                  <td className="num">{r.total}</td>
                  <td className="num">{r.withdrawn}</td>
                  <td className="num">{r.dismissed}</td>
                  <td className="num">{r.attrition_rate !== null ? `${r.attrition_rate}%` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      </section>

      <section className="module">
        <h3>Fee collection status (S-D06)</h3>
        <div className="tiles">
          <div className="tile">
            <span className="num">G${feeTotals.collected.toLocaleString("en-US")}</span>
            <span>Collected</span>
          </div>
          <div className="tile">
            <span className="num">G${(feeTotals.charged - feeTotals.collected).toLocaleString("en-US")}</span>
            <span>Outstanding</span>
          </div>
          <div className="tile">
            <span className="num">{overallCollectionRate !== null ? `${Math.round(overallCollectionRate * 10) / 10}%` : "—"}</span>
            <span>Collection rate</span>
          </div>
        </div>
        {feeGroups.length === 0 ? <p className="muted">No fee charges yet.</p> : <FeeCollectionChart groups={feeGroups} />}
        {unallocated && (
          <p className="muted small">
            G${num(unallocated.collected).toLocaleString("en-US")} in payments fell outside every shown term and is not
            charted above.
          </p>
        )}
      </section>
    </>
  );
}
