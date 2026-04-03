import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Provider } from "urql";
import { client } from "@/lib/urql";
import { AppLayout } from "@/components/layout/AppLayout";
import { Overview } from "@/components/Overview";
import { TraceExplorer } from "@/components/TraceExplorer";
import { TraceDetail } from "@/components/TraceDetail";
import { McpMetrics } from "@/components/McpMetrics";
import { McpList, AgentList, ReviewList, FeedbackPage, EvalsPage, SettingsPage } from "@/pages";
import { Login } from "@/pages/Login";

export default function App() {
  return (
    <Provider value={client}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route element={<AppLayout />}>
            <Route path="/" element={<Overview />} />
            <Route path="/traces" element={<TraceExplorer />} />
            <Route path="/traces/:traceId" element={<TraceDetail />} />
            <Route path="/mcps" element={<McpList />} />
            <Route path="/mcps/:mcpId/metrics" element={<McpMetrics />} />
            <Route path="/agents" element={<AgentList />} />
            <Route path="/reviews" element={<ReviewList />} />
            <Route path="/feedback" element={<FeedbackPage />} />
            <Route path="/evals" element={<EvalsPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </Provider>
  );
}
