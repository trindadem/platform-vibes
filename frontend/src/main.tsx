import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "@/App";
import "@/core/theme.css";

const root = document.getElementById("root");
if (!root) throw new Error('index.html precisa de <div id="root">');

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
