import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "@/App";
import { restoreSession } from "@/core/auth";
import "@/core/theme.css";

// Modo escuro segue o sistema: classe .dark no <html>, como o shadcn/ui espera.
const prefersDark = window.matchMedia("(prefers-color-scheme: dark)");
const applyTheme = () => document.documentElement.classList.toggle("dark", prefersDark.matches);
applyTheme();
prefersDark.addEventListener("change", applyTheme);

// A sessão volta pelo cookie de refresh (o token de acesso nunca é guardado no navegador).
void restoreSession();

const root = document.getElementById("root");
if (!root) throw new Error('index.html precisa de <div id="root">');

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
