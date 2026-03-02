import { Routes, Route } from "react-router-dom";
import IntelflowLayout from "../components/IntelflowLayout";
import Dashboard from "./Dashboard";
import ReportList from "./ReportList";
import ReportDetail from "./ReportDetail";
import SemanticSearch from "./SemanticSearch";
import SmartQA from "./SmartQA";
import TopicsOverview from "./TopicsOverview";
import TopicDetail from "./TopicDetail";
import BriefingSettings from "./BriefingSettings";

export default function IntelflowPages() {
  return (
    <Routes>
      <Route element={<IntelflowLayout />}>
        <Route index element={<Dashboard />} />
        <Route path="reports" element={<ReportList />} />
        <Route path="reports/:id" element={<ReportDetail />} />
        <Route path="search" element={<SemanticSearch />} />
        <Route path="qa" element={<SmartQA />} />
        <Route path="topics" element={<TopicsOverview />} />
        <Route path="topics/:id" element={<TopicDetail />} />
        <Route path="briefings/settings" element={<BriefingSettings />} />
      </Route>
    </Routes>
  );
}
