import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";
import { App } from "./App";
import { ApiError } from "./lib/api";
import { AuthProvider } from "./lib/auth";
import { initSupabase } from "./lib/supabase";
import "./styles/app.css";

const queries = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: (count, error) => count < 2 && !(error instanceof ApiError && error.status < 500),
    },
  },
});

const root = createRoot(document.getElementById("root")!);

initSupabase().then(() => {
  root.render(
    <StrictMode>
      <QueryClientProvider client={queries}>
        <BrowserRouter>
          <AuthProvider>
            <App />
          </AuthProvider>
        </BrowserRouter>
      </QueryClientProvider>
    </StrictMode>,
  );
}).catch((e: Error) => {
  root.render(<main id="view"><div className="page narrow"><div className="card"><h1>MoCA isn't available</h1><p className="error-text">{e.message}</p></div></div></main>);
});
