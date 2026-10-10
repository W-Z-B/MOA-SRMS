import { useCallback, useEffect, useState, type FormEvent } from "react";
import { errorMessage, get, patch, post } from "../../api/client";
import {
  RECORDS_ROLES,
  hasAnyRole,
  type Application,
  type ApplicationDocument,
  type Me,
  type Paginated,
  type Programme,
} from "../../api/types";

interface Props {
  me: Me;
  campusCode: string | null;
}

const STATE_LABEL: Record<string, string> = {
  submitted: "Submitted",
  under_review: "Under review",
  interview: "Interview/assessment scheduled",
  assessed: "Assessed",
  offered: "Offer made",
  waitlisted: "Waitlisted",
  accepted: "Admitted",
  declined: "Declined",
  rejected: "Rejected",
  withdrawn: "Withdrawn",
};

const ACTION_LABEL: Record<string, string> = {
  review: "Move to review",
  schedule_interview: "Schedule interview",
  score: "Mark as assessed",
  offer: "Make offer",
  waitlist: "Add to waitlist",
  promote: "Promote from waitlist",
  accept: "Record acceptance",
  decline: "Record decline",
  reject: "Reject",
  withdraw: "Withdraw",
};

const SECONDARY_ACTIONS = new Set(["reject", "withdraw", "decline"]);

/** Applications with the admissions workflow; the actions shown are the ones the API allows this user. */
export function AdmissionsScreen({ me, campusCode }: Props) {
  const [state, setState] = useState("");
  const [rows, setRows] = useState<Application[]>([]);
  const [programmes, setProgrammes] = useState<Programme[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const load = useCallback(() => {
    const params = new URLSearchParams();
    if (state) params.set("state", state);
    if (campusCode) params.set("campus_code", campusCode);
    Promise.all([get<Paginated<Application>>(`/applications/?${params}`), get<Paginated<Programme>>("/programmes/")])
      .then(([apps, progs]) => {
        setRows(apps.results);
        setProgrammes(progs.results);
        setError(null);
      })
      .catch((err) => setError(errorMessage(err, "Could not load applications.")));
  }, [state, campusCode]);

  useEffect(load, [load]);

  const programmeCode = (id: number) => programmes.find((p) => p.id === id)?.code ?? id;
  const selected = rows.find((r) => r.id === selectedId) ?? null;

  return (
    <div className="split">
      <section>
        <div className="panel-head">
          <h1>Admissions</h1>
          {hasAnyRole(me, RECORDS_ROLES) && <button onClick={() => setAdding(!adding)}>{adding ? "Close form" : "New application"}</button>}
        </div>
        {adding && (
          <ApplicationForm
            programmes={programmes}
            defaultCampus={campusCode}
            onSaved={() => {
              setAdding(false);
              load();
            }}
          />
        )}
        <div className="filters">
          <select id="application-state" value={state} onChange={(e) => setState(e.target.value)}>
            <option value="">Any state</option>
            {Object.entries(STATE_LABEL).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
          <span className="muted">{rows.length} applications</span>
        </div>
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        <table>
          <thead>
            <tr>
              <th>Reference</th>
              <th>Applicant</th>
              <th>Programme</th>
              <th>Campus</th>
              <th>State</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((a) => (
              <tr key={a.id} className={selectedId === a.id ? "selected" : ""} onClick={() => setSelectedId(a.id)}>
                <td>{a.reference}</td>
                <td>{a.full_name}</td>
                <td>{programmeCode(a.programme)}</td>
                <td>{a.campus_code}</td>
                <td>
                  {STATE_LABEL[a.state] ?? a.state}
                  {a.waitlist_rank != null && <span className="pill"> #{a.waitlist_rank}</span>}
                  {a.student_no && <span className="pill"> {a.student_no}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <aside className="panel">
        {selected ? (
          <ApplicationFile key={selected.id} application={selected} onChanged={load} />
        ) : (
          <p className="muted">Select an application to review it.</p>
        )}
      </aside>
    </div>
  );
}

function ApplicationFile({ application, onChanged }: { application: Application; onChanged: () => void }) {
  const [comment, setComment] = useState("");
  const [score, setScore] = useState(application.assessment_score ?? "");
  const [documents, setDocuments] = useState<ApplicationDocument[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const loadDocuments = useCallback(() => {
    get<Paginated<ApplicationDocument>>(`/application-documents/?application=${application.id}`)
      .then((r) => setDocuments(r.results))
      .catch(() => setDocuments([]));
  }, [application.id]);

  useEffect(loadDocuments, [loadDocuments]);

  async function act(action: string) {
    setBusy(true);
    try {
      await post(`/applications/${application.id}/transition/`, { action, comment });
      setComment("");
      onChanged();
    } catch (err) {
      setError(errorMessage(err, "Action failed."));
    } finally {
      setBusy(false);
    }
  }

  async function saveScore(e: FormEvent) {
    e.preventDefault();
    try {
      await patch(`/applications/${application.id}/`, { assessment_score: score });
      onChanged();
    } catch (err) {
      setError(errorMessage(err, "Could not save the score."));
    }
  }

  async function upload(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const file = (form.elements.namedItem("file") as HTMLInputElement).files?.[0];
    if (!file) return;
    const data = new FormData();
    data.set("application", String(application.id));
    data.set("doc_type", (form.elements.namedItem("doc_type") as HTMLSelectElement).value);
    data.set("file", file);
    try {
      await post("/application-documents/", data);
      form.reset();
      loadDocuments();
    } catch (err) {
      setError(errorMessage(err, "Could not upload the document."));
    }
  }

  const needsComment = (action: string) => action === "reject";

  return (
    <>
      <h2>{application.full_name}</h2>
      <p className="muted">
        {application.reference} · {STATE_LABEL[application.state] ?? application.state}
        {application.capacity_remaining != null && <> · {application.capacity_remaining} places left</>}
      </p>
      {error && <p className="error">{error}</p>}

      <h3>Interview / assessment</h3>
      <form className="stack" onSubmit={saveScore}>
        <label>
          Score (0-100)
          <input
            aria-label="Assessment score"
            type="number"
            min={0}
            max={100}
            step="0.01"
            value={score}
            onChange={(e) => setScore(e.target.value)}
          />
        </label>
        {application.assessment_notes && <p className="muted small">{application.assessment_notes}</p>}
        <button type="submit">Save score</button>
      </form>

      <h3>Documents ({documents.length})</h3>
      <ul>
        {documents.map((d) => (
          <li key={d.id}>
            {d.doc_type} {d.note && `· ${d.note}`}
          </li>
        ))}
      </ul>
      <form className="stack" onSubmit={upload}>
        <label>
          Document type
          <select name="doc_type" defaultValue="transcript">
            <option value="transcript">Transcript</option>
            <option value="identification">Identification</option>
            <option value="medical">Medical</option>
            <option value="other">Other</option>
          </select>
        </label>
        <input aria-label="Choose document" type="file" name="file" accept=".pdf,.jpg,.jpeg,.png" required />
        <button type="submit">Upload</button>
      </form>

      <h3>Decision</h3>
      {application.allowed_actions.some(needsComment) && (
        <input aria-label="Decision comment" placeholder="Comment (required to reject)" value={comment} onChange={(e) => setComment(e.target.value)} />
      )}
      <div className="actions">
        {application.allowed_actions.map((action) => (
          <button key={action} disabled={busy} className={SECONDARY_ACTIONS.has(action) ? "secondary" : ""} onClick={() => act(action)}>
            {ACTION_LABEL[action] ?? action}
          </button>
        ))}
      </div>
    </>
  );
}

function ApplicationForm({ programmes, defaultCampus, onSaved }: { programmes: Programme[]; defaultCampus: string | null; onSaved: () => void }) {
  const [form, setForm] = useState({
    first_name: "",
    last_name: "",
    date_of_birth: "",
    gender: "X",
    email: "",
    phone: "",
    qualifications: "",
    programme: "",
    campus_code: defaultCampus ?? "MRP",
    intake_year: String(new Date().getFullYear()),
  });
  const [error, setError] = useState<string | null>(null);
  const set = (key: keyof typeof form, value: string) => setForm({ ...form, [key]: value });

  async function submit(e: FormEvent) {
    e.preventDefault();
    try {
      await post("/applications/", { ...form, programme: Number(form.programme), intake_year: Number(form.intake_year) });
      onSaved();
    } catch (err) {
      setError(errorMessage(err, "Could not save the application."));
    }
  }

  return (
    <form className="card stack" style={{ width: "auto", marginBottom: 16 }} onSubmit={submit}>
      <div className="grid2">
        <label>
          First name
          <input id="app-first" value={form.first_name} onChange={(e) => set("first_name", e.target.value)} required />
        </label>
        <label>
          Last name
          <input id="app-last" value={form.last_name} onChange={(e) => set("last_name", e.target.value)} required />
        </label>
        <label>
          Date of birth
          <input id="app-dob" type="date" value={form.date_of_birth} onChange={(e) => set("date_of_birth", e.target.value)} required />
        </label>
        <label>
          Gender
          <select id="app-gender" value={form.gender} onChange={(e) => set("gender", e.target.value)}>
            <option value="F">Female</option>
            <option value="M">Male</option>
            <option value="X">Other or not stated</option>
          </select>
        </label>
        <label>
          Email
          <input id="app-email" type="email" value={form.email} onChange={(e) => set("email", e.target.value)} />
        </label>
        <label>
          Phone
          <input id="app-phone" value={form.phone} onChange={(e) => set("phone", e.target.value)} />
        </label>
        <label>
          Programme
          <select id="app-programme" value={form.programme} onChange={(e) => set("programme", e.target.value)} required>
            <option value="">Choose</option>
            {programmes.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Campus
          <select id="app-campus" value={form.campus_code} onChange={(e) => set("campus_code", e.target.value)}>
            <option value="MRP">Mon Repos</option>
            <option value="ESQ">Essequibo</option>
          </select>
        </label>
        <label>
          Intake year
          <input id="app-year" type="number" value={form.intake_year} onChange={(e) => set("intake_year", e.target.value)} required />
        </label>
        <label className="span2">
          Entry qualifications
          <textarea id="app-quals" value={form.qualifications} onChange={(e) => set("qualifications", e.target.value)} />
        </label>
      </div>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <div className="actions">
        <button type="submit">Record application</button>
      </div>
    </form>
  );
}
