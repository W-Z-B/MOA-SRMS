import { useCallback, useEffect, useState } from "react";
import { errorMessage, get, patch, post } from "../../api/client";
import type { Me, Offering, Paginated, Result } from "../../api/types";
import { hasAnyRole } from "../../api/types";

interface Props {
  me: Me;
  campusCode: string | null;
}

const STATE_LABEL: Record<string, string> = {
  draft: "Draft",
  submitted: "Submitted",
  dept_reviewed: "Reviewed by department",
  board_approved: "Approved by exam board",
  published: "Published",
};

const ACTION_LABEL: Record<string, string> = {
  submit: "Submit",
  dept_review: "Review",
  board_approve: "Approve",
  publish: "Publish",
  return: "Return",
};

/** Marks entry and the results workflow for one offering. Lecturers see only their own offerings. */
export function ResultsScreen({ me, campusCode }: Props) {
  const [offerings, setOfferings] = useState<Offering[]>([]);
  const [offeringId, setOfferingId] = useState<number | null>(null);
  const [rows, setRows] = useState<Result[]>([]);
  const [edits, setEdits] = useState<Record<number, { coursework_mark?: string; exam_mark?: string }>>({});
  const [comments, setComments] = useState<Record<number, string>>({});
  const [corrections, setCorrections] = useState<
    Record<number, { reason: string; coursework_mark?: string; exam_mark?: string } | undefined>
  >({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const params = new URLSearchParams();
    if (campusCode) params.set("campus_code", campusCode);
    get<Paginated<Offering>>(`/academics/offerings/?${params}`)
      .then((r) => {
        setOfferings(r.results);
        setOfferingId((current) => current ?? r.results[0]?.id ?? null);
        setError(null);
      })
      .catch((err) => setError(errorMessage(err, "Could not load offerings.")));
  }, [campusCode]);

  const load = useCallback(() => {
    if (!offeringId) return;
    get<Paginated<Result>>(`/academics/results/?offering=${offeringId}`)
      .then((r) => {
        setRows(r.results);
        setEdits({});
        setError(null);
      })
      .catch((err) => setError(errorMessage(err, "Could not load results.")));
  }, [offeringId]);

  useEffect(load, [load]);

  async function save(row: Result) {
    const change = edits[row.id];
    if (!change) return;
    try {
      await patch(`/academics/results/${row.id}/`, change);
      load();
    } catch (err) {
      setError(errorMessage(err, "Could not save the marks."));
    }
  }

  async function act(row: Result, action: string) {
    try {
      if (edits[row.id]) await patch(`/academics/results/${row.id}/`, edits[row.id]);
      await post(`/academics/results/${row.id}/transition/`, { action, comment: comments[row.id] ?? "" });
      load();
    } catch (err) {
      setError(errorMessage(err, "Action failed."));
    }
  }

  async function correct(row: Result) {
    const draft = corrections[row.id];
    if (!draft?.reason?.trim()) {
      setError("A reason is required to correct a published result.");
      return;
    }
    try {
      await post(`/academics/results/${row.id}/correct/`, {
        reason: draft.reason,
        coursework_mark: draft.coursework_mark || undefined,
        exam_mark: draft.exam_mark || undefined,
      });
      setCorrections({ ...corrections, [row.id]: undefined } as typeof corrections);
      load();
    } catch (err) {
      setError(errorMessage(err, "Could not correct the result."));
    }
  }

  const isRegistrar = hasAnyRole(me, ["registrar", "administrator"]);
  const offering = offerings.find((o) => o.id === offeringId);
  const canEdit = (row: Result) => row.state === "draft" && row.allowed_actions.includes("submit");
  const value = (row: Result, key: "coursework_mark" | "exam_mark") => edits[row.id]?.[key] ?? row[key] ?? "";
  const change = (row: Result, key: "coursework_mark" | "exam_mark", v: string) =>
    setEdits({ ...edits, [row.id]: { ...edits[row.id], [key]: v } });

  return (
    <>
      <h1>Results</h1>
      <div className="filters">
        <select id="offering" value={offeringId ?? ""} onChange={(e) => setOfferingId(Number(e.target.value))}>
          {offerings.length === 0 && <option value="">No offerings</option>}
          {offerings.map((o) => (
            <option key={o.id} value={o.id}>
              {o.code} ({o.enrolled} enrolled)
            </option>
          ))}
        </select>
        {offering && (
          <span className="muted">
            {offering.course_title} · coursework {offering.coursework_weight}% · examination {offering.exam_weight}% · lecturer{" "}
            {offering.lecturer_employee_no || "not assigned"}
            {me.employee_no === offering.lecturer_employee_no ? " (you)" : ""}
          </span>
        )}
      </div>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {rows.length === 0 ? (
        <p className="muted">No enrolments in this offering.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Student</th>
              <th className="num">Coursework</th>
              <th className="num">Examination</th>
              <th className="num">Final</th>
              <th>Grade</th>
              <th>State</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td>
                  {row.student_no} {row.student_name}
                </td>
                <td className="num">
                  {canEdit(row) ? (
                    <input
                      type="number"
                      min={0}
                      max={100}
                      step="0.01"
                      aria-label={`Coursework mark for ${row.student_no}`}
                      value={value(row, "coursework_mark")}
                      onChange={(e) => change(row, "coursework_mark", e.target.value)}
                    />
                  ) : (
                    (row.coursework_mark ?? "")
                  )}
                  {row.coursework_source === "lms" && <span className="pill">LMS</span>}
                </td>
                <td className="num">
                  {canEdit(row) ? (
                    <input
                      type="number"
                      min={0}
                      max={100}
                      step="0.01"
                      aria-label={`Examination mark for ${row.student_no}`}
                      value={value(row, "exam_mark")}
                      onChange={(e) => change(row, "exam_mark", e.target.value)}
                    />
                  ) : (
                    (row.exam_mark ?? "")
                  )}
                </td>
                <td className="num">{row.final_mark ?? ""}</td>
                <td>{row.letter}</td>
                <td>
                  {STATE_LABEL[row.state] ?? row.state}
                  {row.decision_comment && <span className="muted small"> {row.decision_comment}</span>}
                  {row.correction_count > 0 && (
                    <span className="pill" title="Corrected after publishing">
                      {row.correction_count === 1 ? "1 correction" : `${row.correction_count} corrections`}
                    </span>
                  )}
                </td>
                <td className="actions">
                  {canEdit(row) && edits[row.id] && (
                    <button className="secondary" onClick={() => save(row)}>
                      Save
                    </button>
                  )}
                  {row.allowed_actions.includes("return") && (
                    <input
                      aria-label="Comment for return"
                      placeholder="Comment (required to return)"
                      value={comments[row.id] ?? ""}
                      onChange={(e) => setComments({ ...comments, [row.id]: e.target.value })}
                    />
                  )}
                  {row.allowed_actions.map((action) => (
                    <button key={action} className={action === "return" ? "secondary" : ""} onClick={() => act(row, action)}>
                      {ACTION_LABEL[action] ?? action}
                    </button>
                  ))}
                </td>
              </tr>
            ))}
            {isRegistrar &&
              rows
                .filter((row) => row.state === "published")
                .map((row) => (
                  <tr key={`correct-${row.id}`} className="correction-row">
                    <td colSpan={7}>
                      <details>
                        <summary>
                          Correct {row.student_no}&apos;s published result (reason required, fully audited)
                        </summary>
                        <div className="filters">
                          <input
                            type="number"
                            min={0}
                            max={100}
                            step="0.01"
                            aria-label={`Corrected coursework mark for ${row.student_no}`}
                            placeholder="New coursework"
                            value={corrections[row.id]?.coursework_mark ?? ""}
                            onChange={(e) =>
                              setCorrections({
                                ...corrections,
                                [row.id]: { ...corrections[row.id], reason: corrections[row.id]?.reason ?? "", coursework_mark: e.target.value },
                              })
                            }
                          />
                          <input
                            type="number"
                            min={0}
                            max={100}
                            step="0.01"
                            aria-label={`Corrected examination mark for ${row.student_no}`}
                            placeholder="New examination"
                            value={corrections[row.id]?.exam_mark ?? ""}
                            onChange={(e) =>
                              setCorrections({
                                ...corrections,
                                [row.id]: { ...corrections[row.id], reason: corrections[row.id]?.reason ?? "", exam_mark: e.target.value },
                              })
                            }
                          />
                          <input
                            aria-label={`Reason for correcting ${row.student_no}'s result`}
                            placeholder="Reason (required)"
                            value={corrections[row.id]?.reason ?? ""}
                            onChange={(e) => setCorrections({ ...corrections, [row.id]: { ...corrections[row.id], reason: e.target.value } })}
                          />
                          <button onClick={() => correct(row)}>Correct</button>
                        </div>
                      </details>
                    </td>
                  </tr>
                ))}
          </tbody>
        </table>
      )}
    </>
  );
}
