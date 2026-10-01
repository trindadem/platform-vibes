import { useEffect, useRef, useState } from "react";
import NavigatedViewer from "bpmn-js/lib/NavigatedViewer";
import { Alert } from "./Alert";

export interface BpmnDiagramProps {
  /** O BPMN 2.0 com o desenho (BPMN DI), como o backend devolve. */
  xml: string;
  /** Ids dos elementos percorridos (passos e ligações), pintados com a cor da marca (ex.: o caminho da simulação). */
  highlight?: string[];
  /** Ids dos elementos com problema, contornados em vermelho. */
  problems?: string[];
  /** Nome acessível do diagrama (ex.: "Fluxo do processo Contas a pagar"). */
  label: string;
}

const PERCORRIDO = "cv-percorrido";
const PROBLEMA = "cv-problema";
const ZOOM_MINIMO = 0.7; // abaixo disso o texto some: o fluxo fica legível e o resto se vê arrastando

type Caixa = { x: number; y: number; width: number; height: number };
type Canvas = { zoom: (nivel?: string | number) => number; viewbox: (caixa?: Caixa) => Caixa & { inner: Caixa; outer: Caixa } };

/** Cabe inteiro quando dá; fluxo comprido fica no zoom mínimo, alinhado ao começo (o início do processo). */
function enquadrar(canvas: Canvas) {
  canvas.zoom("fit-viewport");
  if (canvas.zoom() >= ZOOM_MINIMO) return;
  const { inner, outer } = canvas.viewbox();
  canvas.viewbox({ x: inner.x - 20, y: inner.y - 20, width: outer.width / ZOOM_MINIMO, height: outer.height / ZOOM_MINIMO });
}

/**
 * Diagrama BPMN somente leitura (bpmn-js), com zoom e arrasto, o caminho percorrido em destaque e os passos com problema.
 * Fluxo comprido abre legível no começo; o resto se vê arrastando ou com a roda do mouse.
 *
 * @category Dados
 * @example
 * <BpmnDiagram xml={nome} highlight={["inicio", "ler_documento"]} problems={["conferir"]} label="Fluxo do processo" />
 */
export function BpmnDiagram({ xml, highlight = [], problems = [], label }: BpmnDiagramProps) {
  const container = useRef<HTMLDivElement>(null);
  const viewer = useRef<NavigatedViewer | null>(null);
  const marcados = useRef<{ id: string; marker: string }[]>([]);
  const [erro, setErro] = useState<string | null>(null);
  const [pronto, setPronto] = useState(0);

  useEffect(() => {
    if (!container.current) return;
    const instancia = new NavigatedViewer({
      container: container.current,
      bpmnRenderer: { defaultFillColor: "var(--card)", defaultStrokeColor: "var(--foreground)", defaultLabelColor: "var(--foreground)" },
    });
    viewer.current = instancia;
    return () => instancia.destroy();
  }, []);

  useEffect(() => {
    const instancia = viewer.current;
    if (!instancia || !xml) return;
    let ativo = true;
    instancia
      .importXML(xml)
      .then(() => {
        if (!ativo) return;
        marcados.current = [];
        enquadrar(instancia.get("canvas") as Canvas);
        setErro(null);
        setPronto((n) => n + 1);
      })
      .catch((e: unknown) => ativo && setErro(`Não foi possível desenhar o fluxo: ${String(e)}`));
    return () => {
      ativo = false;
    };
  }, [xml]);

  const chave = `${highlight.join(",")}|${problems.join(",")}`;
  useEffect(() => {
    const instancia = viewer.current;
    if (!instancia || !pronto) return;
    const canvas = instancia.get("canvas") as { addMarker: (id: string, m: string) => void; removeMarker: (id: string, m: string) => void };
    const registro = instancia.get("elementRegistry") as { get: (id: string) => unknown };
    for (const { id, marker } of marcados.current) if (registro.get(id)) canvas.removeMarker(id, marker);
    marcados.current = [
      ...highlight.map((id) => ({ id, marker: PERCORRIDO })),
      ...problems.map((id) => ({ id, marker: PROBLEMA })),
    ].filter(({ id }) => registro.get(id));
    for (const { id, marker } of marcados.current) canvas.addMarker(id, marker);
    // chave resume as duas listas: o efeito roda quando elas mudam de conteúdo, não de referência
  }, [chave, pronto]);

  return (
    <div className="flex flex-col gap-2">
      {erro && <Alert tone="danger">{erro}</Alert>}
      <div ref={container} role="img" aria-label={label} className="cv-bpmn h-[60vh] min-h-96 w-full overflow-hidden rounded-xl border border-border bg-card" />
    </div>
  );
}
