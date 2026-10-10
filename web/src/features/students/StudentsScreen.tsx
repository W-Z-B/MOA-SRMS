import { useCallback, useEffect, useState, type FormEvent } from "react";
import { errorMessage, get, post } from "../../api/client";
import {
  RECORDS_ROLES,
  hasAnyRole,
  type Enrolment,
  type Me,
  type Offering,
  type Paginated,
  type RegistrationHold,
  type Student,
  type Transcript,
} from "../../api/types";

interface Props {
  me: Me;
  campusCode: string | null;
  initialId: number | null;
  onNavigate: (to: string) => void;
}

/** Student directory with a file panel: details, audited identifier reveal, transcript. */
export function StudentsScreen({ me, campusCode, initialId, onNavigate }: Props) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [rows, setRows] = useState<Student[]>([]);
  const [count, setCount] = useState(0);
  const [selected, setSelected] = useState<Student | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const params = new URLSearchParams();
    if (query) params.set("q", query);
    if (status) params.set("status", status);
    if (campusCode) params.set("campus_code", campusCode);
    const handle = setTimeout(() => {
      get<Paginated<Student>>(`/students/?${params}`)
        .then((r) => {
          setRows(r.results);
          setCount(r.count);
          setError(null);
        })
        .catch((err) => setError(errorMessage(err, "Could not load students.")));
    }, 250);
    return () => clearTimeout(handle);
  }, [query, status, campusCode]);

  useEffect(() => {
    if (initialId && selected?.id !== initialId) {
      get<Student>(`/students/${initialId}/`).then(setSelected).catch(() => setSelected(null));
    }
  }, [initialId, selected?.id]);

  return (
    <div className="split">
      <section>
        <h1>Students</h1>
        <div className="filters">
          <input id="student-search" placeholder="Search name or student number" value={query} onChange={(e) => setQuery(e.target.value)} />
          <select id="student-status" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">Any status</option>
            <option value="enrolled">Enrolled</option>
            <option value="deferred">Deferred</option>
            <option value="suspended">Suspended</option>
            <option value="withdrawn">Withdrawn</option>
            <option value="graduated">Graduated</option>
          </select>
          <span className="muted">{count} students</span>
        </div>
        {error && <p className="error">{error}</p>}
        <table>
          <thead>
            <tr>
              <th>No.</th>
              <th>Name</th>
              <th>Programme</th>
              <th>Campus</th>
              <th>Intake</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((s) => (
              <tr
                key={s.id}
                className={selected?.id === s.id ? "selected" : ""}
                onClick={() => {
                  setSelected(s);
                  onNavigate(`/students/${s.id}`);
                }}
              >
                <td>{s.student_no}</td>
                <td>{s.full_name}</td>
                <td>{s.programme_code}</td>
                <td>{s.campus_code}</td>
                <td className="num">{s.intake_year}</td>
                <td>{s.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <aside className="panel">
        {selected ? <StudentFile key={selected.id} student={selected} me={me} /> : <p className="muted">Select a student to open their file.</p>}
      </aside>
    </div>
  );
}

function StudentFile({ student, me }: { student: Student; me: Me }) {
  const [tab, setTab] = useState<"details" | "transcript" | "registration">("details");
  const [nationalId, setNationalId] = useState<string | null>(null);
  const [transcript, setTranscript] = useState<Transcript | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (tab !== "transcript") return;
    get<Transcript>(`/students/${student.id}/transcript/`)
      .then((t) => {
        setTranscript(t);
        setError(null);
      })
      .catch((err) => setError(errorMessage(err, "Could not load the transcript.")));
  }, [tab, student.id]);

  async function reveal() {
    try {
      const r = await post<{ national_id: string | null }>(`/students/${student.id}/reveal/`);
      setNationalId(r.national_id ?? "not recorded");
    } catch (err) {
      setError(errorMessage(err, "Reveal failed."));
    }
  }

  return (
    <>
      <h2>{student.full_name}</h2>
      <p className="muted">
        {student.student_no} · {student.programme_name} · {student.campus_code}
      </p>
      <div className="tabs" role="tablist">
        {(["details", "registration", "transcript"] as const).map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "tab active" : "tab"} onClick={() => setTab(t)}>
            {t[0].toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>
      {error && <p className="error">{error}</p>}
      {tab === "details" && (
        <dl>
          <dt>Status</dt>
          <dd>{student.status}</dd>
          <dt>Intake year</dt>
          <dd>{student.intake_year}</dd>
          <dt>Date of birth</dt>
          <dd>{student.date_of_birth}</dd>
          <dt>Email</dt>
          <dd>{student.email || "not recorded"}</dd>
          <dt>Phone</dt>
          <dd>{student.phone || "not recorded"}</dd>
          <dt>Region</dt>
          <dd>{student.region || "not recorded"}</dd>
          <dt>Accommodation</dt>
          <dd>{student.is_residential ? "Residential" : "Day student"}</dd>
          <dt>Sponsor</dt>
          <dd>{student.sponsor}</dd>
          <dt>National ID</dt>
          <dd>{nationalId ?? student.national_id_masked ?? "not recorded"}</dd>
          {hasAnyRole(me, RECORDS_ROLES) && !nationalId && (
            <dd>
              <button className="secondary" onClick={reveal}>
                Reveal identifier (audited)
              </button>
            </dd>
          )}
        </dl>
      )}
      {tab === "registration" && <RegistrationPanel student={student} />}
      {tab === "transcript" && transcript && <TranscriptView transcript={transcript} />}
    </>
  );
}

const HOLD_LABEL: Record<string, string> = {
  missing_document: "Missing document",
  financial: "Outstanding balance",
  academic_standing: "Academic standing",
  other: "Other",
};

/** Course add/drop for a registrar, and the holds that block a new registration (1.46, S-W02). */
function RegistrationPanel({ student }: { student: Student }) {
  const [enrolments, setEnrolments] = useState<Enrolment[]>([]);
  const [holds, setHolds] = useState<RegistrationHold[]>([]);
  const [offerings, setOfferings] = useState<Offering[]>([]);
  const [chosen, setChosen] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    Promise.all([
      get<Paginated<Enrolment>>(`/academics/enrolments/?student=${student.id}`),
      get<Paginated<RegistrationHold>>(`/academics/registration-holds/?student=${student.id}&active=1`),
      get<Paginated<Offering>>(`/academics/offerings/?campus_code=${student.campus_code}`),
    ])
      .then(([e, h, o]) => {
        setEnrolments(e.results);
        setHolds(h.results);
        setOfferings(o.results);
        setError(null);
      })
      .catch((err) => setError(errorMessage(err, "Could not load registration.")));
  }, [student.id, student.campus_code]);

  useEffect(load, [load]);

  async function add(e: FormEvent) {
    e.preventDefault();
    if (!chosen) return;
    try {
      await post("/academics/enrolments/", { student: student.id, offering: Number(chosen) });
      setChosen("");
      load();
    } catch (err) {
      setError(errorMessage(err, "Could not add the course."));
    }
  }

  async function drop(id: number) {
    try {
      await post(`/academics/enrolments/${id}/drop/`);
      load();
    } catch (err) {
      setError(errorMessage(err, "Could not drop the course."));
    }
  }

  const active = enrolments.filter((en) => en.status === "enrolled" || en.status === "waitlisted");
  const alreadyTaken = new Set(active.map((en) => en.offering));

  return (
    <>
      {error && <p className="error">{error}</p>}
      {holds.length > 0 && (
        <div role="alert" className="error">
          <strong>Registration on hold:</strong>
          <ul>
            {holds.map((h) => (
              <li key={h.id}>
                {HOLD_LABEL[h.reason] ?? h.reason_display} ({h.source}){h.detail && ` — ${h.detail}`}
              </li>
            ))}
          </ul>
        </div>
      )}
      <table>
        <thead>
          <tr>
            <th>Offering</th>
            <th>Status</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {active.map((en) => (
            <tr key={en.id}>
              <td>{en.offering_code}</td>
              <td>
                {en.status === "waitlisted" ? `Waitlisted (#${en.waitlist_rank})` : "Enrolled"}
              </td>
              <td>
                <button className="secondary" onClick={() => drop(en.id)}>
                  Drop
                </button>
              </td>
            </tr>
          ))}
          {active.length === 0 && (
            <tr>
              <td colSpan={3} className="muted">
                No courses added yet.
              </td>
            </tr>
          )}
        </tbody>
      </table>
      <form className="stack" onSubmit={add}>
        <label>
          Add a course
          <select aria-label="Choose an offering" value={chosen} onChange={(e) => setChosen(e.target.value)}>
            <option value="">Choose an offering</option>
            {offerings
              .filter((o) => !alreadyTaken.has(o.id))
              .map((o) => (
                <option key={o.id} value={o.id}>
                  {o.code} ({o.enrolled}/{o.capacity})
                </option>
              ))}
          </select>
        </label>
        <button type="submit" disabled={!chosen}>
          Add
        </button>
      </form>
    </>
  );
}

export function TranscriptView({ transcript }: { transcript: Transcript }) {
  if (transcript.terms.length === 0) return <p className="muted">No {transcript.published_only ? "published " : ""}results yet.</p>;
  return (
    <>
      {transcript.terms.map((term) => (
        <section key={term.term}>
          <h3>
            {term.name} <span className="muted small">{term.term}</span>
          </h3>
          <table>
            <thead>
              <tr>
                <th>Course</th>
                <th className="num">Credits</th>
                <th className="num">Mark</th>
                <th>Grade</th>
              </tr>
            </thead>
            <tbody>
              {term.courses.map((c) => (
                <tr key={c.course_code}>
                  <td>
                    {c.course_code} {c.title}
                  </td>
                  <td className="num">{c.credits}</td>
                  <td className="num">{c.final_mark}</td>
                  <td>{c.letter}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted">Term average: {term.gpa ?? "not available"}</p>
        </section>
      ))}
      <p>
        <strong>Cumulative average: {transcript.cumulative_gpa ?? "not available"}</strong>
      </p>
    </>
  );
}
