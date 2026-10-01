/**
 * Vite + trilhos do frontend (README §6). Os trilhos rodam no `npm run dev` e no `npm run build`:
 * violou, a tela de erro (dev) ou o build dizem o arquivo e o que corrigir.
 *
 * - src/modules/<modulo>/page.tsx: só compõe. Sem tag HTML, sem className/style; exporta default e meta.
 * - src/components/<Nome>.tsx: exporta <Nome> com JSDoc e <Nome>Props; não importa core/, modules/ nem App.
 * - src/components/ui/<nome>.tsx: primitivos do shadcn/ui (npx shadcn add <nome>), código de origem preservado.
 *   Só componentes do catálogo os usam; página nunca importa de ui/.
 * - Requisição só em src/core/api.ts; página chama serviços pelas funções de core/contracts.ts (useQuery/useAction).
 * - .css só src/core/theme.css, importado por main.tsx.
 * - Módulo não importa outro módulo. Arquivo fora da topologia é erro.
 *
 * Também gera src/components/CATALOG.md a partir do próprio código (índice por categoria + detalhe com exemplo)
 * e .cv/catalog-examples.tsx, onde o TypeScript confere cada @example no `npm run check`.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, parseSync, type Plugin } from "vite";

const SRC = fileURLToPath(new URL("./src", import.meta.url));
const CATALOG = path.join(SRC, "components", "CATALOG.md");
const EXAMPLES = fileURLToPath(new URL("./.cv/catalog-examples.tsx", import.meta.url));
const GATEWAY = process.env.GATEWAY_URL ?? "http://localhost:8088";

export default defineConfig({
  plugins: [rails(), react(), tailwindcss()],
  resolve: { alias: { "@": SRC } },
  server: { port: 5173, strictPort: true, proxy: { "/api": GATEWAY, "/health": GATEWAY } },
});

// ── Trilhos ──────────────────────────────────────────────────────────────────

type Kind = "component" | "ui" | "module" | "core" | "root";
type Node = { type: string; start: number; end: number; [key: string]: any };
type Comment = { type: string; value: string; start: number; end: number };
interface Violation {
  file: string;
  message: string;
}

const COMPONENT_FILE = /^[A-Z][A-Za-z0-9]*\.tsx$/;
const MODULE_DIR = /^[a-z][a-z0-9]*(-[a-z0-9]+)*$/;
const UI_FILE = /^[a-z][a-z0-9]*(-[a-z0-9]+)*\.tsx?$/;
const CORE_FILES = new Set(["api.ts", "auth.ts", "contracts.ts", "theme.css"]);
const ROOT_FILES = new Set(["App.tsx", "main.tsx"]);
const NETWORK = new Set(["fetch", "XMLHttpRequest", "WebSocket", "EventSource"]);
const HEADER = "Trilhos do frontend violados (README §6):";
// Categorias do catálogo, na ordem do índice. Componente novo escolhe uma delas em @category.
const CATEGORIES: Record<string, string> = {
  Receitas: "telas e dados prontos: comece por aqui",
  Layout: "estrutura da tela",
  Dados: "registros e números",
  Formatação: "dinheiro, datas, status e códigos",
  Formulários: "campos e ações",
  Feedback: "avisos, carregamento e vazio",
  Texto: "títulos e parágrafos",
  Aplicação: "moldura e sessão (usados pelo App.tsx, não pelas páginas)",
};

function rails(): Plugin {
  return {
    name: "cv-frame-rails",
    enforce: "pre",
    buildStart() {
      const violations = scan();
      if (violations.length) this.error(format(violations));
    },
    transform(code, id) {
      const file = id.split("?")[0] ?? id;
      if (!file.startsWith(SRC + path.sep) || !/\.tsx?$/.test(file)) return null;
      const violations = checkSource(file, code);
      if (violations.length) this.error(format(violations));
      return null;
    },
    configureServer(server) {
      // Arquivo novo que ninguém importa não passa pelo transform: o watcher varre a árvore de novo.
      server.watcher.on("all", (_event, file) => {
        if (!file.startsWith(SRC + path.sep) || file === CATALOG) return;
        const violations = scan();
        if (!violations.length) return;
        server.config.logger.error(format(violations));
        server.environments.client.hot.send({ type: "error", err: { message: format(violations), stack: "" } });
      });
    },
  };
}

function format(violations: Violation[]): string {
  return [HEADER, ...violations.map((v) => `  ${v.file}: ${v.message}`)].join("\n");
}

function scan(): Violation[] {
  const violations: Violation[] = [];
  for (const file of listFiles(SRC)) {
    const r = rel(file);
    const parts = r.split("/");
    const ok =
      ROOT_FILES.has(r) ||
      (parts[0] === "core" && parts.length === 2 && CORE_FILES.has(parts[1]!)) ||
      (parts[0] === "components" && parts.length === 2 && (COMPONENT_FILE.test(parts[1]!) || parts[1] === "CATALOG.md")) ||
      (parts[0] === "components" && parts[1] === "ui" && parts.length === 3 && UI_FILE.test(parts[2]!)) ||
      (parts[0] === "modules" && parts.length === 3 && MODULE_DIR.test(parts[1]!) && parts[2] === "page.tsx");
    if (!ok) {
      violations.push({ file: r, message: "arquivo fora da topologia (README §1): componente em src/components/<Nome>.tsx, tela em src/modules/<modulo>/page.tsx" });
    } else if (/\.tsx?$/.test(file)) {
      violations.push(...checkSource(file, fs.readFileSync(file, "utf8")));
    }
  }
  writeCatalog();
  return violations;
}

function checkSource(file: string, code: string): Violation[] {
  const r = rel(file);
  const kind = kindOf(r);
  const { program, comments, errors } = parseSync(file, code);
  if (errors.length || kind === null) return []; // erro de sintaxe: o compilador já reporta
  const violations: Violation[] = [];
  const fail = (message: string) => violations.push({ file: r, message });

  walk(program as Node, (node) => {
    const callee = node.type === "CallExpression" || node.type === "NewExpression" ? calleeName(node.callee) : null;
    if (callee && NETWORK.has(callee) && r !== "core/api.ts") {
      fail(`${callee} fora de src/core/api.ts: use as funções de @/core/contracts com useQuery/useAction`);
    }
    if (node.source?.type === "Literal" && typeof node.source.value === "string") {
      checkImport(node.source.value, file, r, kind, fail);
      const direct = (node.specifiers ?? []).some((s: Node) => s.imported?.name === "request");
      if (kind === "module" && direct && /(^@\/core\/api|\/core\/api)$/.test(node.source.value)) {
        fail("página não chama request: use as funções de @/core/contracts com useQuery/useAction");
      }
    }
    if (kind === "module" && node.type === "JSXOpeningElement" && isIntrinsic(node.name)) {
      fail(`<${node.name.name}> em página: páginas só compõem componentes de src/components (veja CATALOG.md)`);
    }
    if (kind === "module" && node.type === "JSXAttribute" && ["className", "style"].includes(node.name?.name)) {
      fail(`${node.name.name} em página: estilo mora nos componentes; crie ou use um componente`);
    }
  });

  const body = (program as Node).body as Node[];
  if (kind === "component") checkComponent(r, body, comments as Comment[], code, fail);
  if (kind === "module") checkPage(body, fail);
  return violations;
}

function checkImport(spec: string, file: string, r: string, kind: Kind, fail: (m: string) => void) {
  const target = spec.startsWith("@/") ? path.join(SRC, spec.slice(2)) : spec.startsWith(".") ? path.resolve(path.dirname(file), spec) : null;
  const t = target ? rel(target) : spec;
  if (spec.endsWith(".css") && !(r === "main.tsx" && t === "core/theme.css")) {
    fail(`import de ${spec}: o único .css é src/core/theme.css, importado por main.tsx`);
  }
  if (target === null) return;
  const [area, name] = t.split("/");
  if (kind === "module" && area === "components" && name === "ui") {
    fail(`importa ${spec}: página usa o catálogo (src/components/<Nome>.tsx), não os primitivos do shadcn em ui/`);
  }
  if (kind === "ui" && (area !== "components" || name !== "ui")) {
    fail(`importa ${spec}: primitivo de ui/ só depende de pacotes e de outros primitivos de ui/`);
  }
  if (kind === "module" && area === "modules" && name !== r.split("/")[1]) {
    fail(`importa ${spec}: um módulo não importa outro módulo (domínios isolados)`);
  }
  if (kind === "component" && (area === "core" || area === "modules" || ROOT_FILES.has(`${t}.tsx`) || ROOT_FILES.has(t))) {
    fail(`importa ${spec}: componente só apresenta; recebe dados por props (não importa core/, modules/ nem App)`);
  }
  if (kind === "core" && (area === "modules" || area === "components")) {
    fail(`importa ${spec}: core/ não depende de telas nem de componentes`);
  }
}

function checkComponent(r: string, body: Node[], comments: Comment[], code: string, fail: (m: string) => void) {
  const name = path.basename(r, ".tsx");
  const exported = body.filter((n) => n.type === "ExportNamedDeclaration" && n.declaration);
  const fn = exported.find((n) => n.declaration.type === "FunctionDeclaration" && n.declaration.id?.name === name);
  if (!fn) fail(`exporte "export function ${name}(...)", com o mesmo nome do arquivo`);
  const raw = fn ? jsdocBefore(fn, comments, code) : null;
  if (fn && !raw) fail(`documente ${name} com /** ... */ logo acima: é o texto do CATALOG.md`);
  if (raw) {
    const doc = parseDoc(raw);
    if (!doc.summary) fail(`o JSDoc de ${name} começa com uma frase dizendo o que ele é`);
    if (!doc.category || !(doc.category in CATEGORIES)) {
      fail(`JSDoc de ${name} precisa de @category com uma destas: ${Object.keys(CATEGORIES).join(", ")}`);
    }
    if (!doc.example) fail(`JSDoc de ${name} precisa de @example: uma expressão JSX que usa <${name}`);
    else checkExample(name, doc.example, fail);
  }
  if (!exported.some((n) => isTypeDecl(n.declaration) && n.declaration.id?.name === `${name}Props`)) {
    fail(`exporte "${name}Props" (interface ou type) com as props documentadas`);
  }
  if (body.some((n) => n.type === "ExportDefaultDeclaration")) fail("componente usa export nomeado, nunca default");
}

// O exemplo é código de página: JSX válido, usa o próprio componente, sem tag HTML nem className/style.
function checkExample(name: string, example: string, fail: (m: string) => void) {
  const { program, errors } = parseSync("example.tsx", `const exemplo = (\n${example}\n);`);
  if (errors.length) return fail(`@example de ${name} não é uma expressão JSX válida`);
  let usesItself = false;
  walk(program, (node) => {
    if (node.type !== "JSXOpeningElement") return;
    if (node.name?.name === name) usesItself = true;
    if (isIntrinsic(node.name)) fail(`@example de ${name} usa <${node.name.name}>: exemplo segue as regras de página`);
    for (const attr of node.attributes ?? []) {
      if (["className", "style"].includes(attr.name?.name)) fail(`@example de ${name} usa ${attr.name.name}: exemplo segue as regras de página`);
    }
  });
  if (!usesItself) fail(`@example de ${name} precisa usar <${name}`);
}

function checkPage(body: Node[], fail: (m: string) => void) {
  if (!body.some((n) => n.type === "ExportDefaultDeclaration")) fail("page.tsx exporta a tela como default");
  const hasMeta = body.some(
    (n) => n.type === "ExportNamedDeclaration" && n.declaration?.type === "VariableDeclaration" && n.declaration.declarations.some((d: Node) => d.id?.name === "meta"),
  );
  if (!hasMeta) fail('page.tsx exporta "meta": { title: "...", order?: n } (vira o item do menu)');
}

// ── Catálogo ─────────────────────────────────────────────────────────────────

interface Entry {
  name: string;
  summary: string;
  category: string;
  example: string | null;
  props: { name: string; optional: boolean; type: string; doc: string }[];
}

function writeCatalog() {
  const dir = path.join(SRC, "components");
  if (!fs.existsSync(dir)) return;
  const order = Object.keys(CATEGORIES);
  const entries = fs
    .readdirSync(dir)
    .filter((f) => COMPONENT_FILE.test(f))
    .map((f) => describe(path.join(dir, f)))
    .sort((a, b) => rank(order, a.category) - rank(order, b.category) || a.name.localeCompare(b.name));

  const index = order.flatMap((category) => {
    const group = entries.filter((e) => e.category === category);
    if (!group.length) return [];
    return [`**${category}**: ${CATEGORIES[category]}`, "", ...group.map(indexLine), ""];
  });
  const loose = entries.filter((e) => !(e.category in CATEGORIES));
  const content = [
    "# Catálogo de componentes",
    "",
    "> Gerado por `vite.config.ts` a partir de `src/components/*.tsx` em todo `npm run dev` e `npm run build`. Não edite.",
    "> Como usar: leia o índice, escolha as peças (receitas primeiro) e copie o exemplo da seção de cada uma.",
    "> Dados vêm de `useQuery`/`useAction` com as funções de `src/core/contracts.ts`. Faltou peça? Crie",
    "> `src/components/<Nome>.tsx` com JSDoc (frase, `@category`, `@example`) e `<Nome>Props` documentado.",
    "> Os exemplos usam dados fictícios (`faturas`, `lista`, `fatura`, `criar`, `nome`...) e o TypeScript confere cada um.",
    "",
    `## Índice (${entries.length})`,
    "",
    ...index,
    ...(loose.length ? ["**Sem categoria**", "", ...loose.map(indexLine), ""] : []),
    ...entries.flatMap(detail),
  ].join("\n");
  if (!fs.existsSync(CATALOG) || fs.readFileSync(CATALOG, "utf8") !== content) fs.writeFileSync(CATALOG, content);
  writeExamples(entries);
}

function indexLine(e: Entry): string {
  const props = [...e.props.filter((p) => !p.optional), ...e.props.filter((p) => p.optional)];
  const signature = props.map((p) => p.name + (p.optional ? "?" : "")).join(", ");
  return `- [${e.name}](#${e.name.toLowerCase()}): ${e.summary.split(/(?<=\.)\s/)[0]} \`${signature}\``;
}

function detail(e: Entry): string[] {
  return [
    "---",
    "",
    `## ${e.name}`,
    "",
    `${e.summary} _(${e.category || "sem categoria"})_`,
    "",
    ...(e.example ? ["```tsx", e.example, "```", ""] : []),
    ...e.props.map((p) => `- \`${p.name}${p.optional ? "?" : ""}\`: \`${p.type}\`${p.doc ? `: ${p.doc}` : ""}`),
    "",
  ];
}

function describe(file: string): Entry {
  const name = path.basename(file, ".tsx");
  const code = fs.readFileSync(file, "utf8");
  const { program, comments } = parseSync(file, code);
  const body = (program as Node).body as Node[];
  const fn = body.find((n) => n.type === "ExportNamedDeclaration" && n.declaration?.id?.name === name);
  const propsNode = body.find((n) => n.type === "ExportNamedDeclaration" && n.declaration?.id?.name === `${name}Props`);
  const raw = fn ? jsdocBefore(fn, comments as Comment[], code) : null;
  const doc = raw ? parseDoc(raw) : { summary: "", category: "", example: null };
  const members: Node[] = propsNode ? (propsNode.declaration.body?.body ?? propsNode.declaration.typeAnnotation?.members ?? []) : [];
  const props = members
    .filter((m) => m.type === "TSPropertySignature")
    .map((m) => {
      const type = m.typeAnnotation ? code.slice(m.typeAnnotation.typeAnnotation.start, m.typeAnnotation.typeAnnotation.end) : "unknown";
      const propDoc = jsdocBefore(m, comments as Comment[], code);
      return { name: m.key.name, optional: Boolean(m.optional), type: type.replace(/\s+/g, " "), doc: propDoc ? parseDoc(propDoc).summary : "" };
    });
  return { name, summary: doc.summary || "_sem descrição_", category: doc.category ?? "", example: doc.example, props };
}

// Cada @example vira uma expressão num .tsx que o tsc confere: exemplo que mente sobre as props quebra o check.
function writeExamples(entries: Entry[]) {
  const uses = (example: string, name: string) => new RegExp(`<${name}[\\s/>]`).test(example);
  const used = new Set(entries.flatMap((e) => entries.filter((o) => e.example && uses(e.example, o.name)).map((o) => o.name)));
  const content = [
    "// Gerado por vite.config.ts a partir dos @example dos componentes. Não edite; conferido por `npm run check`.",
    'import type { ActionState, ListState, QueryState } from "@/core/api";',
    ...[...used].sort().map((n) => `import { ${n} } from "@/components/${n}";`),
    "",
    "// Dados fictícios que os exemplos usam.",
    'export type Fatura = { id: string; cliente: string; valor: number; status: "aberta" | "paga"; criada_em: string };',
    'export type FaturaIn = { cliente: string; valor: number; status?: "aberta" | "paga" };',
    "export declare const faturas: QueryState<Fatura[]>;",
    "export declare const lista: ListState<Fatura>;",
    "export declare const fatura: QueryState<Fatura>;",
    "export declare const criar: ActionState<[body: FaturaIn], Fatura>;",
    "export declare const nome: string;",
    "export declare function setNome(value: string): void;",
    "export declare const usuario: string | null;",
    "export declare function salvar(): void;",
    "export declare function sair(): void;",
    "",
    "export const exemplos = {",
    // Erro aqui = @example desatualizado no componente indicado no comentário acima dele.
    ...entries.filter((e) => e.example).map((e) => `  // @example de src/components/${e.name}.tsx\n  ${e.name}: (\n${e.example!.replace(/^/gm, "    ")}\n  ),`),
    "};",
    "",
  ].join("\n");
  fs.mkdirSync(path.dirname(EXAMPLES), { recursive: true });
  if (!fs.existsSync(EXAMPLES) || fs.readFileSync(EXAMPLES, "utf8") !== content) fs.writeFileSync(EXAMPLES, content);
}

function rank(order: string[], category: string): number {
  const i = order.indexOf(category);
  return i === -1 ? order.length : i;
}

// ── Utilidades ───────────────────────────────────────────────────────────────

function jsdocBefore(node: Node, comments: Comment[], code: string): string | null {
  const doc = comments.findLast((c) => c.end <= node.start && c.type === "Block" && c.value.startsWith("*"));
  if (!doc || code.slice(doc.end, node.start).trim() !== "") return null;
  return doc.value.replace(/^\*/, "");
}

function parseDoc(raw: string): { summary: string; category: string | null; example: string | null } {
  const summary: string[] = [];
  const example: string[] = [];
  let category: string | null = null;
  let section = "summary";
  for (const line of raw.split("\n").map((l) => l.replace(/^\s*\*\s?/, ""))) {
    const tag = line.match(/^@(\w+)\s*(.*)$/);
    if (tag) {
      section = tag[1]!;
      if (section === "category") category = tag[2]!.trim();
      if (section === "example" && tag[2]) example.push(tag[2]);
      continue;
    }
    if (section === "summary") summary.push(line.trim());
    if (section === "example") example.push(line);
  }
  const text = example.join("\n").replace(/\s+$/, "").replace(/^\n+/, "");
  return { summary: summary.filter(Boolean).join(" "), category, example: text || null };
}

function walk(node: unknown, visit: (n: Node) => void): void {
  if (Array.isArray(node)) return node.forEach((child) => walk(child, visit));
  if (!node || typeof node !== "object") return;
  if (typeof (node as Node).type === "string") visit(node as Node);
  for (const value of Object.values(node)) if (value && typeof value === "object") walk(value, visit);
}

function calleeName(callee: Node): string | null {
  if (callee.type === "Identifier") return callee.name;
  const globals = ["window", "globalThis", "self"];
  if (callee.type === "MemberExpression" && globals.includes(callee.object?.name) && !callee.computed) return callee.property.name;
  return null;
}

function isIntrinsic(name: Node): boolean {
  return (name.type === "JSXIdentifier" && /^[a-z]/.test(name.name)) || name.type === "JSXNamespacedName";
}

function isTypeDecl(node: Node | undefined): boolean {
  return node?.type === "TSInterfaceDeclaration" || node?.type === "TSTypeAliasDeclaration";
}

function kindOf(r: string): Kind | null {
  const area = r.split("/")[0];
  if (r.startsWith("components/ui/")) return "ui";
  if (area === "components") return "component";
  if (area === "modules") return "module";
  if (area === "core") return "core";
  return ROOT_FILES.has(r) ? "root" : null;
}

function rel(file: string): string {
  return path.relative(SRC, file).split(path.sep).join("/");
}

function listFiles(dir: string): string[] {
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    return entry.isDirectory() ? listFiles(full) : [full];
  });
}
