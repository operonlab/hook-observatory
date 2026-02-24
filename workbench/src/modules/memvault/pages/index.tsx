import { Routes, Route } from "react-router-dom";
import MemoryBrowser from "./browser";
import GalaxyPage from "./galaxy";

export default function MemvaultPages() {
  return (
    <Routes>
      <Route index element={<MemoryBrowser />} />
      <Route path="galaxy" element={<GalaxyPage />} />
    </Routes>
  );
}
