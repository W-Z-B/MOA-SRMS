import { useEffect, useState } from "react";
import { errorMessage, get } from "../../api/client";
import type { Transcript } from "../../api/types";
import { TranscriptView } from "../students/StudentsScreen";

/** A student's own published results. */
export function MyResultsScreen() {
  const [transcript, setTranscript] = useState<Transcript | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    get<Transcript>("/academics/my-results/")
      .then((t) => {
        setTranscript(t);
        setError(null);
      })
      .catch((err) => setError(errorMessage(err, "Could not load your results.")));
  }, []);

  return (
    <>
      <h1>My results</h1>
      {error && <p className="error">{error}</p>}
      {transcript && (
        <>
          <p className="muted">
            {transcript.student_no} · {transcript.name} · {transcript.programme}
          </p>
          <TranscriptView transcript={transcript} />
        </>
      )}
    </>
  );
}
