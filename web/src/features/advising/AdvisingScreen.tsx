import { useCallback, useEffect, useState } from "react";
import { errorMessage, get, post } from "../../api/client";
import type { AdvisorAssignment, Paginated, Programme, Student } from "../../api/types";

/** Registrar-facing advisor register, one-at-a-time assignment, and bulk assignment by
 * programme/cohort (S-M04). */
export function AdvisingScreen() {
  const [tab, setTab] = useState<"register" | "assign" | "bulk">("register");
  return (
    <>
      <h1>Academic advising</h1>
      <div className="filters">
        <button className={tab === "register" ? "" : "secondary"} onClick={() => setTab("register")}>
          Advisor register
        </button>
        <button className={tab === "assign" ? "" : "secondary"} onClick={() => setTab("assign")}>
          Assign one student
        </button>
        <button className={tab === "bulk" ? "" : "secondary"} onClick={() => setTab("bulk")}>
          Bulk-assign by cohort
        </button>
      </div>
      {tab === "register" && <Register />}
      {tab === "assign" && <AssignOne />}
      {tab === "bulk" && <BulkAssign />}
    </>
  );
}

function Register() {
  const [rows, setRows] = useState<AdvisorAssignment[]>([]);
  const [advisorFilter, setAdvisorFilter] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    const params = new URLSearchParams({ current: "1" });
    if (advisorFilter) params.set("advisor_employee_no", advisorFilter);
    get<Paginated<AdvisorAssignment>>(`/advising/assignments/?${params}`)
      .then((r) => {
        setRows(r.results);
        setError(null);
      })
      .catch((err) => setError(errorMessage(err, "Could not load the advisor register.")));
  }, [advisorFilter]);

  useEffect(load, [load]);

  async function end(row: AdvisorAssignment) {
    try {
      await post(`/advising/assignments/${row.id}/end/`, {});
      load();
    } catch (err) {
      setError(errorMessage(err, "Could not end this assignment."));
    }
  }

  return (
    <>
      <div className="filters">
        <input
          aria-label="Filter by advisor employee number"
          placeholder="Advisor employee no."
          value={advisorFilter}
          onChange={(e) => setAdvisorFilter(e.target.value)}
        />
      </div>
      {error && <p className="error">{error}</p>}
      {rows.length === 0 ? (
        <p className="muted">No current advisor assignments.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Student</th>
              <th>Programme</th>
              <th>Advisor</th>
              <th>Since</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td>
                  {row.student_no} {row.student_name}
                </td>
                <td>{row.programme_code}</td>
                <td>
                  {row.advisor_employee_no} {row.advisor_name ? `(${row.advisor_name})` : ""}
                </td>
                <td>{new Date(row.started_at).toLocaleDateString()}</td>
                <td>
                  <button className="secondary" onClick={() => end(row)}>
                    End
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

function AssignOne() {
  const [query, setQuery] = useState("");
  const [options, setOptions] = useState<Student[]>([]);
  const [student, setStudent] = useState<Student | null>(null);
  const [advisorEmployeeNo, setAdvisorEmployeeNo] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    if (!query) return;
    const handle = setTimeout(() => {
      get<Paginated<Student>>(`/students/?q=${encodeURIComponent(query)}`)
        .then((r) => setOptions(r.results))
        .catch(() => setOptions([]));
    }, 250);
    return () => clearTimeout(handle);
  }, [query]);

  async function assign() {
    if (!student || !advisorEmployeeNo.trim()) {
      setError("Choose a student and an advisor employee number.");
      return;
    }
    try {
      await post("/advising/assignments/assign/", {
        student: student.id,
        advisor_employee_no: advisorEmployeeNo,
        reason,
      });
      setNotice(`${student.full_name} is now advised by ${advisorEmployeeNo}.`);
      setError(null);
      setStudent(null);
      setQuery("");
      setAdvisorEmployeeNo("");
      setReason("");
    } catch (err) {
      setError(errorMessage(err, "Could not assign the advisor."));
    }
  }

  return (
    <>
      {error && <p className="error">{error}</p>}
      {notice && <p className="muted">{notice}</p>}
      <div className="filters">
        <input
          aria-label="Search for a student"
          placeholder="Search name or student number"
          value={student ? `${student.student_no} ${student.full_name}` : query}
          onChange={(e) => {
            setStudent(null);
            setQuery(e.target.value);
          }}
        />
      </div>
      {!student && query && options.length > 0 && (
        <ul className="suggestions">
          {options.map((s) => (
            <li key={s.id}>
              <button className="link" onClick={() => setStudent(s)}>
                {s.student_no} {s.full_name} ({s.programme_code})
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="filters">
        <input
          aria-label="Advisor employee number"
          placeholder="Advisor employee no. (HRMS)"
          value={advisorEmployeeNo}
          onChange={(e) => setAdvisorEmployeeNo(e.target.value)}
        />
        <input
          aria-label="Reason for this assignment"
          placeholder="Reason (optional)"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
        <button onClick={assign}>Assign</button>
      </div>
    </>
  );
}

function BulkAssign() {
  const [programmes, setProgrammes] = useState<Programme[]>([]);
  const [programme, setProgramme] = useState("");
  const [intakeYear, setIntakeYear] = useState("");
  const [campusCode, setCampusCode] = useState("");
  const [advisorEmployeeNo, setAdvisorEmployeeNo] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ matched: number; assigned: number } | null>(null);

  useEffect(() => {
    get<Paginated<Programme>>("/programmes/").then((r) => setProgrammes(r.results)).catch(() => setProgrammes([]));
  }, []);

  async function submit() {
    if (!advisorEmployeeNo.trim() || (!programme && !intakeYear && !campusCode)) {
      setError("Give an advisor and at least one of programme, intake year or campus.");
      return;
    }
    try {
      const body: Record<string, unknown> = { advisor_employee_no: advisorEmployeeNo };
      if (programme) body.programme = Number(programme);
      if (intakeYear) body.intake_year = Number(intakeYear);
      if (campusCode) body.campus_code = campusCode;
      const r = await post<{ matched: number; assigned: number }>("/advising/assignments/bulk_assign/", body);
      setResult(r);
      setError(null);
    } catch (err) {
      setError(errorMessage(err, "Could not bulk-assign advisees."));
    }
  }

  return (
    <>
      <p className="muted">
        Assign every student matching the filter below to one advisor — a simple sweep, not an auto-matching
        algorithm. A student already assigned to this advisor is left untouched.
      </p>
      {error && <p className="error">{error}</p>}
      {result && (
        <p className="muted">
          {result.matched} student(s) matched; {result.assigned} newly assigned (the rest already had this advisor).
        </p>
      )}
      <div className="filters">
        <select aria-label="Programme" value={programme} onChange={(e) => setProgramme(e.target.value)}>
          <option value="">Any programme</option>
          {programmes.map((p) => (
            <option key={p.id} value={p.id}>
              {p.code}
            </option>
          ))}
        </select>
        <input
          aria-label="Intake year"
          placeholder="Intake year"
          value={intakeYear}
          onChange={(e) => setIntakeYear(e.target.value)}
        />
        <input
          aria-label="Campus code"
          placeholder="Campus code"
          value={campusCode}
          onChange={(e) => setCampusCode(e.target.value)}
        />
        <input
          aria-label="Advisor employee number for bulk assignment"
          placeholder="Advisor employee no. (HRMS)"
          value={advisorEmployeeNo}
          onChange={(e) => setAdvisorEmployeeNo(e.target.value)}
        />
        <button onClick={submit}>Bulk-assign</button>
      </div>
    </>
  );
}
