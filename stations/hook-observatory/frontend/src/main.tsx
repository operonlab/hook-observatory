import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App.tsx";
import "./index.css";

// Detect basename from current path: if served under /apps/hook/, use that.
// Falls back to "/" for local dev (localhost:4101).
const BASE_PATH = window.location.pathname.match(/^(\/apps\/hook)\/?/)?.[1] ?? "";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter basename={BASE_PATH}>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
