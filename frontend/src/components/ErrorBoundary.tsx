// If a page crashes, show what happened and a way out instead of a blank screen.

import { Component, type ReactNode } from "react";

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error) {
    console.error("[MoCA] page crashed:", error);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div className="page narrow"><div className="card">
        <h1>Something went wrong on this page</h1>
        <p className="muted">Reloading usually fixes it. If it keeps happening, send this message to whoever runs the app:</p>
        <p className="error-text">{error.message || String(error)}</p>
        <div className="row">
          <button className="btn primary" onClick={() => window.location.reload()}>Reload</button>
          <button className="btn ghost" onClick={() => window.history.back()}>Go back</button>
        </div>
      </div></div>
    );
  }
}
