// The test itself: a full-screen page that hands over to the runner.

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router";
import { abortTest, runTest } from "../../runner/runner";

export function TakeTest() {
  const { id } = useParams();
  const root = useRef<HTMLElement>(null);
  const navigate = useNavigate();
  const queries = useQueryClient();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    document.body.classList.add("running");
    const sessionId = Number(id);
    // StrictMode mounts twice in development: wait a tick so only the real mount starts the test
    const timer = setTimeout(() => {
      runTest(root.current!, sessionId, () => {
        queries.invalidateQueries({ queryKey: ["sessions"] });
        navigate(`/patient/results/${sessionId}`, { replace: true });
      }).catch((e: Error) => setError(e.message));
    });
    return () => {
      clearTimeout(timer);
      abortTest();
      document.body.classList.remove("running");
    };
  }, [id, navigate, queries]);

  return (
    <main id="view" ref={root}>
      {error && <div className="center-block pad"><h1>This test can't continue</h1><p className="error-text">{error}</p></div>}
    </main>
  );
}
