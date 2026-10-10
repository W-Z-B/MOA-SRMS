import { useEffect, useState } from "react";
import { errorMessage, get } from "../../api/client";
import type { Ledger } from "../../api/types";
import { LedgerView } from "./FeesScreen";

/** A student's own fee balance (S-W07). */
export function MyBalanceScreen() {
  const [ledger, setLedger] = useState<Ledger | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    get<Ledger>("/fees/my-balance/")
      .then((l) => {
        setLedger(l);
        setError(null);
      })
      .catch((err) => setError(errorMessage(err, "Could not load your balance.")));
  }, []);

  return (
    <>
      <h1>My balance</h1>
      {error && <p className="error">{error}</p>}
      {ledger && <LedgerView ledger={ledger} />}
    </>
  );
}
