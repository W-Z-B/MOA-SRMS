import { useCallback, useEffect, useState, type FormEvent } from "react";
import { errorMessage, get, post } from "../../api/client";
import type { Ledger, Paginated, Student } from "../../api/types";

/** A finance officer's student ledger: search, charges and payments, running balance (S-W07). */
export function FeesScreen() {
  const [query, setQuery] = useState("");
  const [rows, setRows] = useState<Student[]>([]);
  const [selected, setSelected] = useState<Student | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const handle = setTimeout(() => {
      const params = new URLSearchParams();
      if (query) params.set("q", query);
      get<Paginated<Student>>(`/students/?${params}`)
        .then((r) => setRows(r.results))
        .catch((err) => setError(errorMessage(err, "Could not load students.")));
    }, 250);
    return () => clearTimeout(handle);
  }, [query]);

  return (
    <div className="split">
      <section>
        <h1>Fees</h1>
        <div className="filters">
          <input
            id="fees-search"
            placeholder="Search name or student number"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        {error && <p className="error">{error}</p>}
        <table>
          <thead>
            <tr>
              <th>No.</th>
              <th>Name</th>
              <th>Programme</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((s) => (
              <tr key={s.id} className={selected?.id === s.id ? "selected" : ""} onClick={() => setSelected(s)}>
                <td>{s.student_no}</td>
                <td>{s.full_name}</td>
                <td>{s.programme_code}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <aside className="panel">
        {selected ? <StudentLedger key={selected.id} student={selected} /> : <p className="muted">Select a student to see their ledger.</p>}
      </aside>
    </div>
  );
}

function StudentLedger({ student }: { student: Student }) {
  const [ledger, setLedger] = useState<Ledger | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({ amount: "", paid_on: new Date().toISOString().slice(0, 10), method: "cash", reference: "", note: "" });

  const load = useCallback(() => {
    get<Ledger>(`/fees/ledger/${student.id}/`)
      .then((l) => {
        setLedger(l);
        setError(null);
      })
      .catch((err) => setError(errorMessage(err, "Could not load the ledger.")));
  }, [student.id]);

  useEffect(load, [load]);

  async function recordPayment(e: FormEvent) {
    e.preventDefault();
    try {
      await post("/fees/payments/", { student: student.id, ...form });
      setForm({ ...form, amount: "", reference: "", note: "" });
      load();
    } catch (err) {
      setError(errorMessage(err, "Could not record the payment."));
    }
  }

  return (
    <>
      <h2>{student.full_name}</h2>
      <p className="muted">
        {student.student_no} · {student.programme_name}
      </p>
      {error && <p className="error">{error}</p>}
      {ledger && <LedgerView ledger={ledger} />}
      <h3>Record a payment</h3>
      <form className="stack" onSubmit={recordPayment}>
        <label>
          Amount
          <input
            aria-label="Payment amount"
            type="number"
            min={0}
            step="0.01"
            value={form.amount}
            onChange={(e) => setForm({ ...form, amount: e.target.value })}
            required
          />
        </label>
        <label>
          Date paid
          <input
            aria-label="Date paid"
            type="date"
            value={form.paid_on}
            onChange={(e) => setForm({ ...form, paid_on: e.target.value })}
            required
          />
        </label>
        <label>
          Method
          <select aria-label="Payment method" value={form.method} onChange={(e) => setForm({ ...form, method: e.target.value })}>
            <option value="cash">Cash</option>
            <option value="bank_transfer">Bank transfer</option>
            <option value="cheque">Cheque</option>
            <option value="other">Other</option>
          </select>
        </label>
        <label>
          Reference
          <input value={form.reference} onChange={(e) => setForm({ ...form, reference: e.target.value })} />
        </label>
        <button type="submit">Record payment</button>
      </form>
    </>
  );
}

export function LedgerView({ ledger }: { ledger: Ledger }) {
  return (
    <>
      <p>
        <strong>Balance: {ledger.balance}</strong>
      </p>
      {ledger.entries.length === 0 ? (
        <p className="muted">No charges or payments yet.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Date</th>
              <th>Description</th>
              <th className="num">Amount</th>
              <th className="num">Balance</th>
            </tr>
          </thead>
          <tbody>
            {ledger.entries.map((e, i) => (
              <tr key={i}>
                <td>{e.date}</td>
                <td>{e.description}</td>
                <td className="num">{e.amount}</td>
                <td className="num">{e.running_balance}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
