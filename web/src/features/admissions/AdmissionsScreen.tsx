import { useCallback, useEffect, useState, type FormEvent } from "react";
import { errorMessage, get, post } from "../../api/client";
import { RECORDS_ROLES, hasAnyRole, type Application, type Me, type Paginated, type Programme } from "../../api/types";

interface Props {
  me: Me;
  campusCode: string | null;
}

const STATE_LABEL: Record<string, string> = {
  received: "Received",
  screened: "Screened",
  offered: "Offer made",
  accepted: "Admitted",
  rejected: "Rejected",
  withdrawn: "Withdrawn",
};

/** Applications with the admissions workflow; the actions shown are the ones the API allows this user. */
export function AdmissionsScreen({ me, campusCode }: Props) {
  const [state, setState] = useState("");
  const [rows, setRows] = useState<Application[]>([]);
  const [programmes, setProgrammes] = useState<Programme[]>([]);
  const [comments, setComments] = useState<Record<number, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

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

  async function act(id: number, action: string) {
    try {
      await post(`/applications/${id}/transition/`, { action, comment: comments[id] ?? "" });
      load();
    } catch (err) {
      setError(errorMessage(err, "Action failed."));
    }
  }

  const programmeCode = (id: number) => programmes.find((p) => p.id === id)?.code ?? id;

  return (
    <>
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
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((a) => (
            <tr key={a.id}>
              <td>{a.reference}</td>
              <td>{a.full_name}</td>
              <td>{programmeCode(a.programme)}</td>
              <td>{a.campus_code}</td>
              <td>
                {STATE_LABEL[a.state] ?? a.state}
                {a.student_no && <span className="pill"> {a.student_no}</span>}
                {a.decision_comment && <span className="muted small"> {a.decision_comment}</span>}
              </td>
              <td className="actions">
                {a.allowed_actions.includes("reject") && (
                  <input
                    aria-label="Rejection comment"
                    placeholder="Comment (required to reject)"
                    value={comments[a.id] ?? ""}
                    onChange={(e) => setComments({ ...comments, [a.id]: e.target.value })}
                  />
                )}
                {a.allowed_actions.map((action) => (
                  <button key={action} className={["reject", "withdraw"].includes(action) ? "secondary" : ""} onClick={() => act(a.id, action)}>
                    {action}
                  </button>
                ))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
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
