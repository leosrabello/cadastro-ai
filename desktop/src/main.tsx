import "@fontsource-variable/bricolage-grotesque";
import "./styles.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { HashRouter, Navigate, Route, Routes } from "react-router-dom";
import { ApiError } from "./api/client";
import { AuthProvider, useAuth } from "./auth";
import { Shell } from "./components/Shell";
import { ToastProvider } from "./components/ui";
import { Dashboard } from "./screens/Dashboard";
import { DocumentReview } from "./screens/DocumentReview";
import { History } from "./screens/History";
import { Inbox } from "./screens/Inbox";
import { Landing } from "./screens/Landing";
import { Login } from "./screens/Login";
import { Queue } from "./screens/Queue";
import { RegistrationDetail } from "./screens/RegistrationDetail";
import { Registrations } from "./screens/Registrations";
import { Report } from "./screens/Report";
import { Settings } from "./screens/Settings";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (count, err) => !(err instanceof ApiError && err.status >= 400 && err.status < 500) && count < 2,
      refetchOnWindowFocus: true,
    },
  },
});

function Routed() {
  const { signedIn } = useAuth();
  if (!signedIn) {
    return (
      <Routes>
        <Route index element={<Landing />} />
        <Route path="entrar" element={<Login />} />
        <Route path="*" element={<Navigate to="/entrar" replace />} />
      </Routes>
    );
  }
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<Dashboard />} />
        <Route path="fila" element={<Queue />} />
        <Route path="cadastros" element={<Registrations />} />
        <Route path="cadastros/:id" element={<RegistrationDetail />} />
        <Route path="cadastros/:id/relatorio" element={<Report />} />
        <Route path="documentos/:id" element={<DocumentReview />} />
        <Route path="entrada" element={<Inbox />} />
        <Route path="historico" element={<History />} />
        <Route path="configuracoes" element={<Settings />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <AuthProvider>
          <HashRouter>
            <Routed />
          </HashRouter>
        </AuthProvider>
      </ToastProvider>
    </QueryClientProvider>
  </StrictMode>,
);
