// Gerado por gateway/contracts.py a partir de gateway/endpoints/*.yaml e services/*/schemas.py. Não edite:
// depois de mudar um manifesto ou um schemas.py, rode (da raiz) `uv run python gateway/contracts.py`.
import { request, stream, withQuery, type RequestOptions, type ResourceMeta, type StreamOptions } from "./api";

/** Resposta de toda rota NATS: o id da mensagem publicada (o mesmo para a mesma Idempotency-Key). */
export interface Dispatched {
  message_id: string;
}

/** Um registro de cadastro pelo id (core/resources.py). */
export interface ResourceRef {
  id: string;
}

/** Resposta da remoção de um registro de cadastro. */
export interface ResourceRemoved {
  id: string;
}

/** Aviso ao vivo de um cadastro (<serviço>.<cadastro>): a lista aberta busca de novo. */
export interface ResourceChanged {
  id: string;
  action: "created" | "updated" | "removed";
}

/** GET /health do gateway (README §5.18). */
export interface GatewayHealth {
  /** "ok" quando tudo responde (senão, a resposta é um erro 503). */
  status: string;
  /** Cada dependência do gateway e se respondeu ("ok"). */
  checks: Record<string, string>;
  /** Quantas rotas os manifestos publicam. */
  routes: number;
}

/** Rotas do próprio gateway. */
export const gateway = {
  /** GET /health · pública */
  health: (options?: RequestOptions) => request<GatewayHealth>("GET", "/health", undefined, options),
};

export interface AgentesAgente {
  id: string;
  nome: string;
  descricao: string;
  instrucao: string;
  modelo: string;
  ferramentas: AgentesFerramentaAgente[];
  casos: AgentesCaso[];
  /** verificado: passou na suíte; confiável: o staff decidiu */
  status: "rascunho" | "verificado" | "confiavel";
  /** Sobe a cada mudança no que o agente faz; a avaliação vale para uma versão */
  versao: number;
  avaliando: boolean;
  avaliacao: AgentesAvaliacao | null;
  confiavel_por: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface AgentesAvaliacao {
  versao: number;
  ok: boolean;
  resultados: AgentesResultadoCaso[];
  em: string;
}

/** Um caso da suíte: dada a tarefa e os dados, o agente devolve o esperado. */
export interface AgentesCaso {
  id: string;
  nome: string;
  tarefa: string;
  /** O que o passo teria à mão (ex.: ler_documento.*) */
  dados: Record<string, unknown>;
  /** Campo → valor que o agente precisa devolver */
  esperado: Record<string, string | number | boolean>;
}

export interface AgentesFerramentaAgente {
  ref: string;
  /** perguntar: o agente não usa sozinho; o passo vai para uma pessoa aprovar */
  modo: "permitir" | "perguntar";
}

export interface AgentesResultadoCaso {
  caso: string;
  ok: boolean;
  saida: Record<string, unknown>;
  detalhes: string[];
  /** O que o agente chamou */
  ferramentas: string[];
}

export interface AgentesAgentes {
  itens: AgentesAgente[];
}

export interface AgentesAgenteRef {
  id: string;
}

export interface AgentesNovoAgente {
  nome: string;
  descricao?: string;
  instrucao: string;
  modelo?: string;
  ferramentas?: AgentesFerramentaAgente[];
  casos?: AgentesCaso[];
}

export interface AgentesEdicaoAgente {
  id: string;
  nome?: string | null;
  descricao?: string | null;
  instrucao?: string | null;
  modelo?: string | null;
  ferramentas?: AgentesFerramentaAgente[] | null;
  casos?: AgentesCaso[] | null;
}

/** Experimentar o agente na tela, com uma tarefa e dados quaisquer. */
export interface AgentesTeste {
  id: string;
  tarefa: string;
  dados?: Record<string, unknown>;
  /** Campo → tipo do que ele devolve */
  saidas: Record<string, "texto" | "numero" | "sim_nao">;
}

export interface AgentesExecucao {
  saidas: Record<string, unknown>;
  fontes: Record<string, string>;
  /** O agente pediu ajuda: o motivo */
  ajuda: string | null;
  /** A política pede aprovação de uma pessoa para o que ele ia fazer */
  aprovacao: string | null;
  /** O que ele chamou, na ordem */
  ferramentas: string[];
  /** O que ele leu (documentos e respostas das ferramentas) */
  lidos: string[];
  texto: string;
}

export interface AgentesFerramentaCatalogo {
  /** conhecimento, documento ou mcp:<servidor>:<ferramenta> */
  ref: string;
  nome: string;
  descricao: string;
  origem: "plataforma" | "mcp";
  servidor_nome: string | null;
  risco: "leitura" | "escrita" | "externa" | "irreversivel";
  parametros: Record<string, unknown>;
}

export interface AgentesCatalogoFerramentas {
  itens: AgentesFerramentaCatalogo[];
  /** Falso quando o svc-integracoes não respondeu (só as da plataforma) */
  integracoes: boolean;
}

export interface AgentesAgenteMudou {
  id: string;
  action: "criado" | "alterado" | "avaliando" | "avaliado" | "confiavel" | "removido";
}

/** svc-agentes · /api/v1/agentes */
export const agentes = {
  /** GET /api/v1/agentes/agentes · http · exige token */
  lista: (options?: RequestOptions) =>
    request<AgentesAgentes>("GET", "/api/v1/agentes/agentes", undefined, options),
  /** GET /api/v1/agentes/agentes/item · http · exige token */
  agente: (query?: AgentesAgenteRef, options?: RequestOptions) =>
    request<AgentesAgente>("GET", withQuery("/api/v1/agentes/agentes/item", query), undefined, options),
  /** POST /api/v1/agentes/agentes · http · exige token */
  criar: (body: AgentesNovoAgente, options?: RequestOptions) =>
    request<AgentesAgente>("POST", "/api/v1/agentes/agentes", body, options),
  /** POST /api/v1/agentes/agentes/editar · http · exige token */
  editar: (body: AgentesEdicaoAgente, options?: RequestOptions) =>
    request<AgentesAgente>("POST", "/api/v1/agentes/agentes/editar", body, options),
  /** POST /api/v1/agentes/agentes/remover · http · exige token */
  remover: (body: AgentesAgenteRef, options?: RequestOptions) =>
    request<AgentesAgente>("POST", "/api/v1/agentes/agentes/remover", body, options),
  /** POST /api/v1/agentes/agentes/avaliar · http · exige token */
  avaliar: (body: AgentesAgenteRef, options?: RequestOptions) =>
    request<AgentesAgente>("POST", "/api/v1/agentes/agentes/avaliar", body, options),
  /** POST /api/v1/agentes/agentes/confiar · http · exige token */
  confiar: (body: AgentesAgenteRef, options?: RequestOptions) =>
    request<AgentesAgente>("POST", "/api/v1/agentes/agentes/confiar", body, options),
  /** POST /api/v1/agentes/agentes/testar · http · exige token */
  testar: (body: AgentesTeste, options?: RequestOptions) =>
    request<AgentesExecucao>("POST", "/api/v1/agentes/agentes/testar", body, options),
  /** GET /api/v1/agentes/ferramentas · http · exige token */
  ferramentas: (options?: RequestOptions) =>
    request<AgentesCatalogoFerramentas>("GET", "/api/v1/agentes/ferramentas", undefined, options),
};

export interface AiProvider {
  id: string;
  name: string;
  slug: string;
  /** Vazio no provedor da plataforma visto por outra organização */
  base_url: string;
  /** Só os últimos 4 caracteres da chave (vazio no provedor da plataforma visto de fora) */
  key_hint: string;
  scope: "organization" | "platform";
}

export interface AiProviderList {
  items: AiProvider[];
  /** Quem pede administra os provedores da plataforma */
  manages_platform: boolean;
}

export interface AiProviderInput {
  /** Nome para exibir */
  name: string;
  /** Apelido usado no nome do modelo (ex.: openrouter → openrouter/claude) */
  slug: string;
  /** Endereço base da API compatível com OpenAI (ex.: https://openrouter.ai/api/v1) */
  base_url: string;
  /** Chave do provedor (vazia para provedores locais sem chave) */
  api_key?: string;
  /** organization (só a sua organização) ou platform (todas) */
  scope?: "organization" | "platform";
}

export interface AiProviderRef {
  id: string;
}

export interface AiDiscovered {
  /** Modelos que o provedor listou */
  found: number;
  /** Novos no catálogo (nascem não liberados) */
  added: number;
}

export interface AiModel {
  id: string;
  /** O que se passa ao llm.*: <provedor>/<apelido ou id> */
  name: string;
  provider: string;
  model_id: string;
  alias: string | null;
  kind: "chat" | "embedding";
  enabled: boolean;
  price_input: number;
  price_output: number;
  scope: "organization" | "platform";
}

export interface AiModelPage {
  items: AiModel[];
  /** Itens que atendem ao filtro, somando todas as páginas */
  total: number;
  page: number;
  size: number;
  /** Total de páginas (0 quando não há itens) */
  pages: number;
}

/** Lista de modelos: busca por id ou apelido, filtros de liberado e tipo. Membro só recebe os liberados. */
export interface AiModelQuery {
  /** Página, a partir de 1 */
  page?: number;
  /** Itens por página (até 100) */
  size?: number;
  /** Ordem: "campo" (crescente) ou "-campo" (decrescente) */
  sort?: "model_id" | "-model_id" | "alias" | "-alias" | null;
  /** Busca por palavras (início de palavra, sem acento) */
  q?: string | null;
  /** Só liberados (true) ou só não liberados (false) */
  enabled?: boolean | null;
  kind?: "chat" | "embedding" | null;
}

export interface AiModelInput {
  /** Id do provedor */
  provider: string;
  model_id: string;
  kind?: "chat" | "embedding";
}

export interface AiModelUpdate {
  id: string;
  enabled?: boolean | null;
  /** Nome curto (ex.: claude → openrouter/claude); vazio remove o apelido */
  alias?: string | null;
  kind?: "chat" | "embedding" | null;
  /** Preço por milhão de tokens de entrada */
  price_input?: number | null;
  /** Preço por milhão de tokens de saída */
  price_output?: number | null;
}

export interface AiUsageItem {
  model: string;
  service: string;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  cost: number;
}

export interface AiUsageSummary {
  /** AAAA-MM, em UTC */
  month: string;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  cost: number;
  items: AiUsageItem[];
}

/** Uso gravado (também vai ao vivo para a tela da organização). */
export interface AiRecorded {
  id: string;
  model: string;
  service: string;
  cost: number;
  at: string;
}

/** svc-ai · /api/v1/ai */
export const ai = {
  /** GET /api/v1/ai/providers · http · exige token */
  providers: (options?: RequestOptions) =>
    request<AiProviderList>("GET", "/api/v1/ai/providers", undefined, options),
  /** POST /api/v1/ai/providers · http · exige token */
  createProvider: (body: AiProviderInput, options?: RequestOptions) =>
    request<AiProvider>("POST", "/api/v1/ai/providers", body, options),
  /** POST /api/v1/ai/providers/remove · http · exige token */
  removeProvider: (body: AiProviderRef, options?: RequestOptions) =>
    request<AiProviderList>("POST", "/api/v1/ai/providers/remove", body, options),
  /** POST /api/v1/ai/providers/discover · http · exige token */
  discoverModels: (body: AiProviderRef, options?: RequestOptions) =>
    request<AiDiscovered>("POST", "/api/v1/ai/providers/discover", body, options),
  /** GET /api/v1/ai/models · http · exige token */
  models: (query?: AiModelQuery, options?: RequestOptions) =>
    request<AiModelPage>("GET", withQuery("/api/v1/ai/models", query), undefined, options),
  /** POST /api/v1/ai/models · http · exige token */
  addModel: (body: AiModelInput, options?: RequestOptions) =>
    request<AiModel>("POST", "/api/v1/ai/models", body, options),
  /** POST /api/v1/ai/models/update · http · exige token */
  updateModel: (body: AiModelUpdate, options?: RequestOptions) =>
    request<AiModel>("POST", "/api/v1/ai/models/update", body, options),
  /** GET /api/v1/ai/usage · http · exige token */
  usage: (options?: RequestOptions) =>
    request<AiUsageSummary>("GET", "/api/v1/ai/usage", undefined, options),
};

export interface ConhecimentoMensagem {
  id: string;
  papel: "cliente" | "agente";
  texto: string;
  /** O que o agente fez para responder */
  passos: string[];
  created_at: string | null;
}

/** O perfil da empresa. Todo campo é opcional: o briefing vai preenchendo; vazio apaga. */
export interface ConhecimentoPerfil {
  atividade: string | null;
  /** Ex.: padaria, clínica, indústria de embalagens */
  segmento: string | null;
  porte: "mei" | "micro" | "pequena" | "media" | "grande" | null;
  cidade: string | null;
  uf: string | null;
  site: string | null;
  produtos: string | null;
  clientes: string | null;
  canais_venda: string | null;
  bancos: string | null;
  /** Boleto, Pix, cartão, prazo... */
  recebimentos: string | null;
  pagamentos: string | null;
  /** Escritório contábil ou interna */
  contabilidade: string | null;
  regime_tributario: "mei" | "simples" | "presumido" | "real" | "nao_sei" | null;
  sistemas: string | null;
  /** NF, boletos, contratos */
  documentos: string | null;
  colaboradores: number | null;
  equipe: string | null;
  dores: string | null;
  objetivos: string | null;
}

export interface ConhecimentoTopico {
  id: string;
  titulo: string;
  status: "feito" | "em_andamento" | "a_fazer";
  /** Rótulos do que falta para o tópico ficar feito */
  faltam: string[];
}

export interface ConhecimentoBriefing {
  perfil: ConhecimentoPerfil;
  topicos: ConhecimentoTopico[];
  mensagens: ConhecimentoMensagem[];
  concluido_em: string | null;
  pode_concluir: boolean;
}

export interface ConhecimentoMensagemIn {
  /** O que a pessoa escreveu */
  texto: string;
}

/** Um passo do agente enquanto responde (pedaço do stream). */
export interface ConhecimentoPasso {
  ferramenta: string;
  texto: string;
  status: "running" | "done" | "failed";
}

export interface ConhecimentoEmpty {
}

export interface ConhecimentoAchado {
  id: string;
  titulo: string;
  trecho: string;
  fonte: "briefing" | "site" | "documento" | "manual";
  origem: string | null;
  nota: number;
}

export interface ConhecimentoAchados {
  itens: ConhecimentoAchado[];
}

export interface ConhecimentoBuscaQuery {
  /** Palavras da busca, em qualquer ordem */
  q: string;
}

/** O passo de briefing e conhecimento da jornada, para o workspace. */
export interface ConhecimentoResumo {
  topicos_feitos: number;
  topicos_total: number;
  concluido_em: string | null;
  itens: number;
  /** Itens por fonte (briefing, site, documento, manual) */
  por_fonte: Record<string, number>;
  leituras_lendo: number;
}

export interface ConhecimentoSiteIn {
  /** Endereço do site (com ou sem https://) */
  url: string;
}

export interface ConhecimentoLeitura {
  id: string;
  tipo: "site" | "documento";
  /** Endereço do site ou nome do arquivo */
  origem: string;
  status: "lendo" | "pronta" | "falhou";
  paginas: number;
  itens: number;
  erro: string | null;
  created_at: string | null;
  updated_at: string | null;
}

/** O que a tela diz antes de enviar: nome, tipo e tamanho do arquivo (o envio só vale para esse tamanho e tipo). */
export interface ConhecimentoUploadRequest {
  filename: string;
  content_type: string;
  /** Tamanho em bytes */
  size: number;
}

/** Link de envio: a tela faz PUT do arquivo em url com estes cabeçalhos e depois confirma a key no serviço. */
export interface ConhecimentoUpload {
  key: string;
  url: string;
  /** Cabeçalhos que o PUT precisa levar exatamente assim */
  headers: Record<string, string>;
  expires_at: string;
}

export interface ConhecimentoKeepRequest {
  /** A key devolvida em Upload */
  key: string;
}

export interface ConhecimentoLeituraPage {
  items: ConhecimentoLeitura[];
  /** Itens que atendem ao filtro, somando todas as páginas */
  total: number;
  page: number;
  size: number;
  /** Total de páginas (0 quando não há itens) */
  pages: number;
}

export interface ConhecimentoLeituraQuery {
  /** Página, a partir de 1 */
  page?: number;
  /** Itens por página (até 100) */
  size?: number;
  /** Ordem: "campo" (crescente) ou "-campo" (decrescente) */
  sort?: "created_at" | "-created_at" | "origem" | "-origem" | null;
  /** Busca por palavras (início de palavra, sem acento) */
  q?: string | null;
  tipo?: "site" | "documento" | null;
  status?: "lendo" | "pronta" | "falhou" | null;
}

export interface ConhecimentoLeituraRef {
  id: string;
}

export interface ConhecimentoLeituraMudou {
  id: string;
  status: "lendo" | "pronta" | "falhou" | "removida";
}

export interface ConhecimentoBriefingMudou {
  action: "mensagem" | "perfil" | "concluido" | "reaberto";
}

/** Um item da base de conhecimento: um assunto, com a fonte de onde veio. */
export interface ConhecimentoConhecimento {
  titulo: string;
  conteudo: string;
  tipo?: "empresa" | "produto" | "cliente" | "fornecedor" | "processo" | "politica" | "contato" | "outro";
  /** De onde veio: briefing, site, documento ou manual */
  fonte?: "briefing" | "site" | "documento" | "manual";
  /** Endereço ou arquivo de onde veio */
  origem?: string | null;
  /** Ex.: tabela de preços ou contrato com vencimento */
  validade?: string | null;
}

/** Conhecimento: só os campos que mudam. */
export interface ConhecimentoConhecimentoUpdate {
  /** Id do registro */
  id: string;
  titulo?: string | null;
  conteudo?: string | null;
  tipo?: "empresa" | "produto" | "cliente" | "fornecedor" | "processo" | "politica" | "contato" | "outro" | null;
  /** De onde veio: briefing, site, documento ou manual */
  fonte?: "briefing" | "site" | "documento" | "manual" | null;
  /** Endereço ou arquivo de onde veio */
  origem?: string | null;
  /** Ex.: tabela de preços ou contrato com vencimento */
  validade?: string | null;
}

/** Conhecimento: página, busca, filtros e ordem pela URL. */
export interface ConhecimentoConhecimentoQuery {
  /** Página, a partir de 1 */
  page?: number;
  /** Itens por página (até 100) */
  size?: number;
  /** Ordem: "campo" (crescente) ou "-campo" (decrescente) */
  sort?: "titulo" | "-titulo" | "validade" | "-validade" | "created_at" | "-created_at" | null;
  /** Busca por palavras (início de palavra, sem acento) */
  q?: string | null;
  tipo?: "empresa" | "produto" | "cliente" | "fornecedor" | "processo" | "politica" | "contato" | "outro" | null;
  fonte?: "briefing" | "site" | "documento" | "manual" | null;
}

/** Conhecimento: um registro. */
export interface ConhecimentoConhecimentoItem {
  /** Id do registro */
  id: string;
  created_at: string | null;
  created_by: string | null;
  updated_at: string | null;
  updated_by: string | null;
  titulo: string;
  conteudo: string;
  tipo: "empresa" | "produto" | "cliente" | "fornecedor" | "processo" | "politica" | "contato" | "outro";
  /** De onde veio: briefing, site, documento ou manual */
  fonte: "briefing" | "site" | "documento" | "manual";
  /** Endereço ou arquivo de onde veio */
  origem: string | null;
  /** Ex.: tabela de preços ou contrato com vencimento */
  validade: string | null;
}

export interface ConhecimentoConhecimentoPage {
  items: ConhecimentoConhecimentoItem[];
  /** Itens que atendem ao filtro, somando todas as páginas */
  total: number;
  page: number;
  size: number;
  /** Total de páginas (0 quando não há itens) */
  pages: number;
}

/** svc-conhecimento · /api/v1/conhecimento */
export const conhecimento = {
  /** GET /api/v1/conhecimento/briefing · http · exige token */
  briefing: (options?: RequestOptions) =>
    request<ConhecimentoBriefing>("GET", "/api/v1/conhecimento/briefing", undefined, options),
  /** POST /api/v1/conhecimento/briefing/mensagem · http · em pedaços (options.onDelta) · exige token */
  mensagem: (body: ConhecimentoMensagemIn, options?: StreamOptions<ConhecimentoPasso>) =>
    stream<ConhecimentoPasso, ConhecimentoBriefing>("POST", "/api/v1/conhecimento/briefing/mensagem", body, options),
  /** POST /api/v1/conhecimento/briefing/perfil · http · exige token */
  salvarPerfil: (body: ConhecimentoPerfil, options?: RequestOptions) =>
    request<ConhecimentoBriefing>("POST", "/api/v1/conhecimento/briefing/perfil", body, options),
  /** POST /api/v1/conhecimento/briefing/concluir · http · exige token */
  concluir: (body: ConhecimentoEmpty, options?: RequestOptions) =>
    request<ConhecimentoBriefing>("POST", "/api/v1/conhecimento/briefing/concluir", body, options),
  /** POST /api/v1/conhecimento/briefing/reabrir · http · exige token */
  reabrir: (body: ConhecimentoEmpty, options?: RequestOptions) =>
    request<ConhecimentoBriefing>("POST", "/api/v1/conhecimento/briefing/reabrir", body, options),
  /** GET /api/v1/conhecimento/busca · http · exige token */
  busca: (query?: ConhecimentoBuscaQuery, options?: RequestOptions) =>
    request<ConhecimentoAchados>("GET", withQuery("/api/v1/conhecimento/busca", query), undefined, options),
  /** GET /api/v1/conhecimento/resumo · http · exige token */
  resumo: (options?: RequestOptions) =>
    request<ConhecimentoResumo>("GET", "/api/v1/conhecimento/resumo", undefined, options),
  /** POST /api/v1/conhecimento/site · http · exige token */
  lerSite: (body: ConhecimentoSiteIn, options?: RequestOptions) =>
    request<ConhecimentoLeitura>("POST", "/api/v1/conhecimento/site", body, options),
  /** POST /api/v1/conhecimento/documentos/upload · http · exige token */
  documentoUpload: (body: ConhecimentoUploadRequest, options?: RequestOptions) =>
    request<ConhecimentoUpload>("POST", "/api/v1/conhecimento/documentos/upload", body, options),
  /** POST /api/v1/conhecimento/documentos · http · exige token */
  lerDocumento: (body: ConhecimentoKeepRequest, options?: RequestOptions) =>
    request<ConhecimentoLeitura>("POST", "/api/v1/conhecimento/documentos", body, options),
  /** GET /api/v1/conhecimento/leituras · http · exige token */
  leituras: (query?: ConhecimentoLeituraQuery, options?: RequestOptions) =>
    request<ConhecimentoLeituraPage>("GET", withQuery("/api/v1/conhecimento/leituras", query), undefined, options),
  /** POST /api/v1/conhecimento/leituras/remove · http · exige token */
  removerLeitura: (body: ConhecimentoLeituraRef, options?: RequestOptions) =>
    request<ConhecimentoLeituraMudou>("POST", "/api/v1/conhecimento/leituras/remove", body, options),
  /** Cadastro Conhecimento (core/resources.py) · /api/v1/conhecimento/itens · exige token */
  itens: {
    /** GET /api/v1/conhecimento/itens · página, busca, filtros e ordem */
    list: (query?: ConhecimentoConhecimentoQuery, options?: RequestOptions) =>
      request<ConhecimentoConhecimentoPage>("GET", withQuery("/api/v1/conhecimento/itens", query), undefined, options),
    /** GET /api/v1/conhecimento/itens/item?id= */
    get: (query: ResourceRef, options?: RequestOptions) =>
      request<ConhecimentoConhecimentoItem>("GET", withQuery("/api/v1/conhecimento/itens/item", query), undefined, options),
    /** POST /api/v1/conhecimento/itens */
    create: (body: ConhecimentoConhecimento, options?: RequestOptions) =>
      request<ConhecimentoConhecimentoItem>("POST", "/api/v1/conhecimento/itens", body, options),
    /** POST /api/v1/conhecimento/itens/update · só os campos que vierem mudam */
    update: (body: ConhecimentoConhecimentoUpdate, options?: RequestOptions) =>
      request<ConhecimentoConhecimentoItem>("POST", "/api/v1/conhecimento/itens/update", body, options),
    /** POST /api/v1/conhecimento/itens/remove */
    remove: (body: ResourceRef, options?: RequestOptions) =>
      request<ResourceRemoved>("POST", "/api/v1/conhecimento/itens/remove", body, options),
    /** Campos, colunas e filtros: o que useResource e ResourceList usam para montar a tela. */
    meta: {"title": "Conhecimento", "live": "conhecimento.itens", "fields": [{"name": "titulo", "label": "Título", "kind": "text", "required": true}, {"name": "conteudo", "label": "Conteúdo", "kind": "textarea", "required": true}, {"name": "tipo", "label": "Tipo", "kind": "select", "required": false, "options": [{"value": "empresa", "label": "Empresa"}, {"value": "produto", "label": "Produto ou serviço"}, {"value": "cliente", "label": "Cliente"}, {"value": "fornecedor", "label": "Fornecedor"}, {"value": "processo", "label": "Processo"}, {"value": "politica", "label": "Política ou regra"}, {"value": "contato", "label": "Contato"}, {"value": "outro", "label": "Outro"}]}, {"name": "fonte", "label": "Fonte", "kind": "select", "required": false, "options": [{"value": "briefing", "label": "Briefing"}, {"value": "site", "label": "Site"}, {"value": "documento", "label": "Documento"}, {"value": "manual", "label": "Manual"}], "hint": "De onde veio: briefing, site, documento ou manual"}, {"name": "origem", "label": "Origem", "kind": "text", "required": false, "hint": "Endereço ou arquivo de onde veio"}, {"name": "validade", "label": "Vale até", "kind": "date", "required": false, "hint": "Ex.: tabela de preços ou contrato com vencimento"}], "columns": [{"key": "titulo", "header": "Título", "kind": "text", "sort": "titulo"}, {"key": "tipo", "header": "Tipo", "kind": "select"}, {"key": "fonte", "header": "Fonte", "kind": "select"}, {"key": "origem", "header": "Origem", "kind": "text"}, {"key": "validade", "header": "Vale até", "kind": "date", "sort": "validade"}], "filters": [{"name": "tipo", "label": "Tipo", "options": [{"value": "empresa", "label": "Empresa"}, {"value": "produto", "label": "Produto ou serviço"}, {"value": "cliente", "label": "Cliente"}, {"value": "fornecedor", "label": "Fornecedor"}, {"value": "processo", "label": "Processo"}, {"value": "politica", "label": "Política ou regra"}, {"value": "contato", "label": "Contato"}, {"value": "outro", "label": "Outro"}]}, {"name": "fonte", "label": "Fonte", "options": [{"value": "briefing", "label": "Briefing"}, {"value": "site", "label": "Site"}, {"value": "documento", "label": "Documento"}, {"value": "manual", "label": "Manual"}]}], "search": "título, conteúdo"} satisfies ResourceMeta,
  },
};

/** Uma conta a pagar que o processo agendou: do agendamento à conciliação. */
export interface FinanceiroTitulo {
  id: string;
  fornecedor: string | null;
  valor: number;
  vencimento: string | null;
  /** Data agendada no banco */
  data: string;
  pagamento_id: string;
  status: "agendado" | "pago";
  created_at: string | null;
  updated_at: string | null;
}

export interface FinanceiroTituloPage {
  items: FinanceiroTitulo[];
  /** Itens que atendem ao filtro, somando todas as páginas */
  total: number;
  page: number;
  size: number;
  /** Total de páginas (0 quando não há itens) */
  pages: number;
}

export interface FinanceiroTituloQuery {
  /** Página, a partir de 1 */
  page?: number;
  /** Itens por página (até 100) */
  size?: number;
  /** Ordem: "campo" (crescente) ou "-campo" (decrescente) */
  sort?: "created_at" | "-created_at" | "data" | "-data" | "valor" | "-valor" | null;
  /** Busca por palavras (início de palavra, sem acento) */
  q?: string | null;
  status?: "agendado" | "pago" | null;
}

export interface FinanceiroTituloMudou {
  id: string;
  action: "agendado" | "pago";
}

export interface FinanceiroFornecedor {
  nome: string;
  cnpj?: string | null;
  conta?: string;
  centro_custo?: string | null;
  /** Mensal; documento com outro valor diverge */
  valor_contrato?: number | null;
}

/** Fornecedores: só os campos que mudam. */
export interface FinanceiroFornecedorUpdate {
  /** Id do registro */
  id: string;
  nome?: string | null;
  cnpj?: string | null;
  conta?: string | null;
  centro_custo?: string | null;
  /** Mensal; documento com outro valor diverge */
  valor_contrato?: number | null;
}

/** Fornecedores: página, busca, filtros e ordem pela URL. */
export interface FinanceiroFornecedorQuery {
  /** Página, a partir de 1 */
  page?: number;
  /** Itens por página (até 100) */
  size?: number;
  /** Ordem: "campo" (crescente) ou "-campo" (decrescente) */
  sort?: "nome" | "-nome" | "created_at" | "-created_at" | null;
  /** Busca por palavras (início de palavra, sem acento) */
  q?: string | null;
}

/** Fornecedores: um registro. */
export interface FinanceiroFornecedorItem {
  /** Id do registro */
  id: string;
  created_at: string | null;
  created_by: string | null;
  updated_at: string | null;
  updated_by: string | null;
  nome: string;
  cnpj: string | null;
  conta: string;
  centro_custo: string | null;
  /** Mensal; documento com outro valor diverge */
  valor_contrato: number | null;
}

export interface FinanceiroFornecedorPage {
  items: FinanceiroFornecedorItem[];
  /** Itens que atendem ao filtro, somando todas as páginas */
  total: number;
  page: number;
  size: number;
  /** Total de páginas (0 quando não há itens) */
  pages: number;
}

/** svc-financeiro · /api/v1/financeiro */
export const financeiro = {
  /** GET /api/v1/financeiro/titulos · http · exige token */
  titulos: (query?: FinanceiroTituloQuery, options?: RequestOptions) =>
    request<FinanceiroTituloPage>("GET", withQuery("/api/v1/financeiro/titulos", query), undefined, options),
  /** Cadastro Fornecedores (core/resources.py) · /api/v1/financeiro/fornecedores · exige token */
  fornecedores: {
    /** GET /api/v1/financeiro/fornecedores · página, busca, filtros e ordem */
    list: (query?: FinanceiroFornecedorQuery, options?: RequestOptions) =>
      request<FinanceiroFornecedorPage>("GET", withQuery("/api/v1/financeiro/fornecedores", query), undefined, options),
    /** GET /api/v1/financeiro/fornecedores/item?id= */
    get: (query: ResourceRef, options?: RequestOptions) =>
      request<FinanceiroFornecedorItem>("GET", withQuery("/api/v1/financeiro/fornecedores/item", query), undefined, options),
    /** POST /api/v1/financeiro/fornecedores */
    create: (body: FinanceiroFornecedor, options?: RequestOptions) =>
      request<FinanceiroFornecedorItem>("POST", "/api/v1/financeiro/fornecedores", body, options),
    /** POST /api/v1/financeiro/fornecedores/update · só os campos que vierem mudam */
    update: (body: FinanceiroFornecedorUpdate, options?: RequestOptions) =>
      request<FinanceiroFornecedorItem>("POST", "/api/v1/financeiro/fornecedores/update", body, options),
    /** POST /api/v1/financeiro/fornecedores/remove */
    remove: (body: ResourceRef, options?: RequestOptions) =>
      request<ResourceRemoved>("POST", "/api/v1/financeiro/fornecedores/remove", body, options),
    /** Campos, colunas e filtros: o que useResource e ResourceList usam para montar a tela. */
    meta: {"title": "Fornecedores", "live": "financeiro.fornecedores", "fields": [{"name": "nome", "label": "Nome", "kind": "text", "required": true}, {"name": "cnpj", "label": "CNPJ", "kind": "text", "required": false}, {"name": "conta", "label": "Conta do plano de contas", "kind": "text", "required": false}, {"name": "centro_custo", "label": "Centro de custo", "kind": "text", "required": false}, {"name": "valor_contrato", "label": "Valor do contrato", "kind": "money", "required": false, "hint": "Mensal; documento com outro valor diverge"}], "columns": [{"key": "nome", "header": "Nome", "kind": "text", "sort": "nome"}, {"key": "cnpj", "header": "CNPJ", "kind": "text"}, {"key": "conta", "header": "Conta do plano de contas", "kind": "text"}, {"key": "centro_custo", "header": "Centro de custo", "kind": "text"}, {"key": "valor_contrato", "header": "Valor do contrato", "kind": "money"}], "filters": [], "search": "nome, cnpj"} satisfies ResourceMeta,
  },
};

export interface IdentitySignupInput {
  /** Nome da pessoa */
  name: string;
  /** E-mail de acesso */
  email: string;
  /** Senha (mínimo de 8 caracteres) */
  password: string;
  /** Nome da organização nova (quem cadastra vira dono) */
  organization?: string | null;
  /** Código de convite (entra numa organização existente) */
  invite?: string | null;
}

export interface IdentityTenant {
  id: string;
  name: string;
  roles: ("owner" | "admin" | "member" | "operador")[];
}

export interface IdentityUser {
  id: string;
  name: string;
  email: string;
}

export interface IdentityAuthResult {
  /** Token de acesso (Authorization: Bearer) */
  access_token: string;
  /** Segundos até o token de acesso expirar */
  expires_in: number;
  user: IdentityUser;
  /** Organização ativa */
  tenant: IdentityTenant | null;
  /** Todas as organizações do usuário */
  tenants: IdentityTenant[];
}

export interface IdentityLoginInput {
  email: string;
  password: string;
  /** Organização para entrar (padrão: a última usada) */
  tenant?: string | null;
}

export interface IdentityEmpty {
}

export interface IdentityInviteCode {
  /** Código do convite */
  code: string;
}

export interface IdentityInviteInfo {
  tenant_name: string;
  role: "owner" | "admin" | "member" | "operador";
  expires_at: string;
}

export interface IdentityForgotInput {
  /** E-mail da conta */
  email: string;
}

export interface IdentityResetInput {
  /** Código do link recebido por e-mail */
  code: string;
  /** Senha nova (mínimo de 8 caracteres) */
  password: string;
}

export interface IdentityMe {
  user: IdentityUser;
  tenant: string | null;
  tenants: IdentityTenant[];
}

export interface IdentitySwitchInput {
  /** Organização que passa a ser a ativa */
  tenant: string;
}

export interface IdentityTenantInput {
  /** Nome da organização */
  name: string;
}

export interface IdentityInviteInput {
  /** Papel de quem aceitar o convite (o operador vem só da carteira do staff) */
  role?: "admin" | "member";
  /** Se informado, o convite também vai por e-mail para este endereço */
  email?: string | null;
}

export interface IdentityInvite {
  /** Código para o link de convite (mostrado uma única vez) */
  code: string;
  role: "owner" | "admin" | "member" | "operador";
  expires_at: string;
  /** Para quem o convite foi enviado por e-mail */
  email: string | null;
}

export interface IdentityMember {
  id: string;
  name: string;
  email: string;
  roles: ("owner" | "admin" | "member" | "operador")[];
  joined_at: string;
}

export interface IdentityMemberList {
  items: IdentityMember[];
}

export interface IdentityMemberRef {
  /** Id do usuário */
  user: string;
}

export interface IdentityOrganization {
  id: string;
  name: string;
  /** Link assinado da imagem do logo (vale 1 h) */
  logo_url: string | null;
  /** Cor da marca (#RRGGBB): a tela a usa como cor principal; null: a da plataforma */
  color: string | null;
}

/** O que a tela diz antes de enviar: nome, tipo e tamanho do arquivo (o envio só vale para esse tamanho e tipo). */
export interface IdentityUploadRequest {
  filename: string;
  content_type: string;
  /** Tamanho em bytes */
  size: number;
}

/** Link de envio: a tela faz PUT do arquivo em url com estes cabeçalhos e depois confirma a key no serviço. */
export interface IdentityUpload {
  key: string;
  url: string;
  /** Cabeçalhos que o PUT precisa levar exatamente assim */
  headers: Record<string, string>;
  expires_at: string;
}

export interface IdentityKeepRequest {
  /** A key devolvida em Upload */
  key: string;
}

export interface IdentityColorInput {
  /** #RRGGBB; null volta à cor da plataforma */
  color: string | null;
}

export interface IdentityMembersChanged {
  /** Id de quem entrou ou saiu */
  user: string;
  change: "joined" | "removed";
}

export interface IdentityAccessChanged {
  /** Organização que a pessoa deixou de acessar */
  tenant: string;
  change: "removed";
}

/** svc-identity · /api/v1/identity */
export const identity = {
  /** POST /api/v1/identity/signup · http · pública · sessão em cookie */
  signup: (body: IdentitySignupInput, options?: RequestOptions) =>
    request<IdentityAuthResult>("POST", "/api/v1/identity/signup", body, options),
  /** POST /api/v1/identity/login · http · pública · sessão em cookie */
  login: (body: IdentityLoginInput, options?: RequestOptions) =>
    request<IdentityAuthResult>("POST", "/api/v1/identity/login", body, options),
  /** POST /api/v1/identity/refresh · http · pública · sessão em cookie */
  refresh: (body: IdentityEmpty, options?: RequestOptions) =>
    request<IdentityAuthResult>("POST", "/api/v1/identity/refresh", body, options),
  /** POST /api/v1/identity/logout · http · pública · sessão em cookie */
  logout: (body: IdentityEmpty, options?: RequestOptions) =>
    request<IdentityEmpty>("POST", "/api/v1/identity/logout", body, options),
  /** POST /api/v1/identity/invite-info · http · pública */
  inviteInfo: (body: IdentityInviteCode, options?: RequestOptions) =>
    request<IdentityInviteInfo>("POST", "/api/v1/identity/invite-info", body, options),
  /** POST /api/v1/identity/password/forgot · http · pública */
  forgotPassword: (body: IdentityForgotInput, options?: RequestOptions) =>
    request<IdentityEmpty>("POST", "/api/v1/identity/password/forgot", body, options),
  /** POST /api/v1/identity/password/reset · http · pública */
  resetPassword: (body: IdentityResetInput, options?: RequestOptions) =>
    request<IdentityEmpty>("POST", "/api/v1/identity/password/reset", body, options),
  /** GET /api/v1/identity/me · http · exige token */
  me: (options?: RequestOptions) =>
    request<IdentityMe>("GET", "/api/v1/identity/me", undefined, options),
  /** POST /api/v1/identity/switch · http · exige token · sessão em cookie */
  switchTenant: (body: IdentitySwitchInput, options?: RequestOptions) =>
    request<IdentityAuthResult>("POST", "/api/v1/identity/switch", body, options),
  /** POST /api/v1/identity/tenants · http · exige token · sessão em cookie */
  createTenant: (body: IdentityTenantInput, options?: RequestOptions) =>
    request<IdentityAuthResult>("POST", "/api/v1/identity/tenants", body, options),
  /** POST /api/v1/identity/join · http · exige token · sessão em cookie */
  join: (body: IdentityInviteCode, options?: RequestOptions) =>
    request<IdentityAuthResult>("POST", "/api/v1/identity/join", body, options),
  /** POST /api/v1/identity/invites · http · exige token */
  createInvite: (body: IdentityInviteInput, options?: RequestOptions) =>
    request<IdentityInvite>("POST", "/api/v1/identity/invites", body, options),
  /** GET /api/v1/identity/members · http · exige token */
  members: (options?: RequestOptions) =>
    request<IdentityMemberList>("GET", "/api/v1/identity/members", undefined, options),
  /** POST /api/v1/identity/members/remove · http · exige token */
  removeMember: (body: IdentityMemberRef, options?: RequestOptions) =>
    request<IdentityMemberList>("POST", "/api/v1/identity/members/remove", body, options),
  /** GET /api/v1/identity/organization · http · exige token */
  organization: (options?: RequestOptions) =>
    request<IdentityOrganization>("GET", "/api/v1/identity/organization", undefined, options),
  /** POST /api/v1/identity/organization/logo/upload · http · exige token */
  logoUpload: (body: IdentityUploadRequest, options?: RequestOptions) =>
    request<IdentityUpload>("POST", "/api/v1/identity/organization/logo/upload", body, options),
  /** POST /api/v1/identity/organization/logo · http · exige token */
  setLogo: (body: IdentityKeepRequest, options?: RequestOptions) =>
    request<IdentityOrganization>("POST", "/api/v1/identity/organization/logo", body, options),
  /** POST /api/v1/identity/organization/color · http · exige token */
  setColor: (body: IdentityColorInput, options?: RequestOptions) =>
    request<IdentityOrganization>("POST", "/api/v1/identity/organization/color", body, options),
  /** POST /api/v1/identity/organization/logo/remove · http · exige token */
  removeLogo: (body: unknown, options?: RequestOptions) =>
    request<IdentityOrganization>("POST", "/api/v1/identity/organization/logo/remove", body, options),
};

export interface IntegracoesConexao {
  id: string;
  tipo: "caixa_entrada" | "banco_simulado";
  nome: string;
  /** caixa_entrada: para onde encaminhar boletos e notas */
  endereco: string | null;
  /** banco_simulado: segundos até o banco confirmar um pagamento */
  confirmar_apos: number | null;
  created_at: string | null;
}

export interface IntegracoesConexoes {
  itens: IntegracoesConexao[];
}

export interface IntegracoesNovaConexao {
  tipo: "caixa_entrada" | "banco_simulado";
  nome?: string | null;
  /** banco_simulado: segundos até confirmar o pagamento */
  confirmar_apos?: number;
}

export interface IntegracoesConexaoRef {
  id: string;
}

export interface IntegracoesResumo {
  /** Endereço da caixa de entrada, se conectada */
  caixa_entrada: string | null;
  banco: boolean;
  documentos: number;
  agendados: number;
}

export interface IntegracoesDocumento {
  id: string;
  origem: "email";
  de: string | null;
  assunto: string | null;
  nome: string;
  tipo: string;
  tamanho: number;
  /** Falso em imagem ou PDF escaneado: o agente não lê (sem OCR) */
  tem_texto: boolean;
  created_at: string | null;
}

export interface IntegracoesDocumentoPage {
  items: IntegracoesDocumento[];
  /** Itens que atendem ao filtro, somando todas as páginas */
  total: number;
  page: number;
  size: number;
  /** Total de páginas (0 quando não há itens) */
  pages: number;
}

export interface IntegracoesDocumentoQuery {
  /** Página, a partir de 1 */
  page?: number;
  /** Itens por página (até 100) */
  size?: number;
  /** Ordem: "campo" (crescente) ou "-campo" (decrescente) */
  sort?: "created_at" | "-created_at" | "nome" | "-nome" | null;
  /** Busca por palavras (início de palavra, sem acento) */
  q?: string | null;
}

export interface IntegracoesLink {
  url: string;
  nome: string;
  tipo: string;
}

export interface IntegracoesDocumentoRef {
  id: string;
}

export interface IntegracoesPagamento {
  id: string;
  pagamento_id: string;
  valor: number;
  /** Data agendada (AAAA-MM-DD) */
  data: string;
  fornecedor: string | null;
  linha_digitavel: string | null;
  status: "agendado" | "pago";
  pago_em: string | null;
  created_at: string | null;
}

export interface IntegracoesPagamentoPage {
  items: IntegracoesPagamento[];
  /** Itens que atendem ao filtro, somando todas as páginas */
  total: number;
  page: number;
  size: number;
  /** Total de páginas (0 quando não há itens) */
  pages: number;
}

export interface IntegracoesPagamentoQuery {
  /** Página, a partir de 1 */
  page?: number;
  /** Itens por página (até 100) */
  size?: number;
  /** Ordem: "campo" (crescente) ou "-campo" (decrescente) */
  sort?: "created_at" | "-created_at" | "data" | "-data" | "valor" | "-valor" | null;
  /** Busca por palavras (início de palavra, sem acento) */
  q?: string | null;
  status?: "agendado" | "pago" | null;
}

export interface IntegracoesPagamentoRef {
  id: string;
}

export interface IntegracoesItemCatalogo {
  tipo: string;
  nome: string;
  descricao: string;
  disponivel: boolean;
  /** A organização pode ter mais de uma */
  varias: boolean;
}

export interface IntegracoesCatalogo {
  itens: IntegracoesItemCatalogo[];
}

/** Uma ferramenta anunciada pelo servidor, sanitizada e pinada (a impressão de nome, descrição e schema). */
export interface IntegracoesFerramentaMcp {
  nome: string;
  titulo: string | null;
  descricao: string;
  /** JSON schema da entrada */
  parametros: Record<string, unknown>;
  /** Piso externa: o que o servidor diz de si só sobe o risco */
  risco: "leitura" | "escrita" | "externa" | "irreversivel";
  digest: string;
  /** Por que a ferramenta não pode ser usada (mudou, texto oculto...) */
  quarentena: string | null;
}

export interface IntegracoesServidorMcp {
  id: string;
  nome: string;
  url: string;
  /** Cabeçalho que leva a credencial (ex.: Authorization) */
  cabecalho: string | null;
  tem_segredo: boolean;
  ferramentas: IntegracoesFerramentaMcp[];
  /** Nome e versão que o servidor informou */
  servidor: string | null;
  atualizado_em: string | null;
  created_at: string | null;
}

export interface IntegracoesServidoresMcp {
  itens: IntegracoesServidorMcp[];
}

export interface IntegracoesNovoServidorMcp {
  nome: string;
  /** Endereço MCP (Streamable HTTP), https */
  url: string;
  cabecalho?: string | null;
  /** Valor do cabeçalho (ex.: Bearer abc...): guardado cifrado */
  segredo?: string | null;
}

export interface IntegracoesServidorRef {
  id: string;
}

export interface IntegracoesConexaoMudou {
  id: string;
  action: "conectada" | "removida";
}

export interface IntegracoesDocumentoMudou {
  id: string;
  action: "recebido";
}

export interface IntegracoesPagamentoMudou {
  id: string;
  action: "agendado" | "pago";
}

export interface IntegracoesServidorMudou {
  id: string;
  action: "conectado" | "atualizado" | "removido" | "quarentena";
}

/** svc-integracoes · /api/v1/integracoes */
export const integracoes = {
  /** GET /api/v1/integracoes/conexoes · http · exige token */
  conexoes: (options?: RequestOptions) =>
    request<IntegracoesConexoes>("GET", "/api/v1/integracoes/conexoes", undefined, options),
  /** POST /api/v1/integracoes/conexoes · http · exige token */
  conectar: (body: IntegracoesNovaConexao, options?: RequestOptions) =>
    request<IntegracoesConexao>("POST", "/api/v1/integracoes/conexoes", body, options),
  /** POST /api/v1/integracoes/conexoes/remover · http · exige token */
  desconectar: (body: IntegracoesConexaoRef, options?: RequestOptions) =>
    request<IntegracoesConexao>("POST", "/api/v1/integracoes/conexoes/remover", body, options),
  /** GET /api/v1/integracoes/resumo · http · exige token */
  resumo: (options?: RequestOptions) =>
    request<IntegracoesResumo>("GET", "/api/v1/integracoes/resumo", undefined, options),
  /** GET /api/v1/integracoes/documentos · http · exige token */
  documentos: (query?: IntegracoesDocumentoQuery, options?: RequestOptions) =>
    request<IntegracoesDocumentoPage>("GET", withQuery("/api/v1/integracoes/documentos", query), undefined, options),
  /** GET /api/v1/integracoes/documentos/arquivo · http · exige token */
  arquivo: (query?: IntegracoesDocumentoRef, options?: RequestOptions) =>
    request<IntegracoesLink>("GET", withQuery("/api/v1/integracoes/documentos/arquivo", query), undefined, options),
  /** GET /api/v1/integracoes/pagamentos · http · exige token */
  pagamentos: (query?: IntegracoesPagamentoQuery, options?: RequestOptions) =>
    request<IntegracoesPagamentoPage>("GET", withQuery("/api/v1/integracoes/pagamentos", query), undefined, options),
  /** POST /api/v1/integracoes/pagamentos/confirmar · http · exige token */
  confirmarPagamento: (body: IntegracoesPagamentoRef, options?: RequestOptions) =>
    request<IntegracoesPagamento>("POST", "/api/v1/integracoes/pagamentos/confirmar", body, options),
  /** GET /api/v1/integracoes/catalogo · http · exige token */
  catalogo: (options?: RequestOptions) =>
    request<IntegracoesCatalogo>("GET", "/api/v1/integracoes/catalogo", undefined, options),
  /** GET /api/v1/integracoes/servidores · http · exige token */
  servidores: (options?: RequestOptions) =>
    request<IntegracoesServidoresMcp>("GET", "/api/v1/integracoes/servidores", undefined, options),
  /** POST /api/v1/integracoes/servidores · http · exige token */
  conectarServidor: (body: IntegracoesNovoServidorMcp, options?: RequestOptions) =>
    request<IntegracoesServidorMcp>("POST", "/api/v1/integracoes/servidores", body, options),
  /** POST /api/v1/integracoes/servidores/atualizar · http · exige token */
  atualizarServidor: (body: IntegracoesServidorRef, options?: RequestOptions) =>
    request<IntegracoesServidorMcp>("POST", "/api/v1/integracoes/servidores/atualizar", body, options),
  /** POST /api/v1/integracoes/servidores/remover · http · exige token */
  removerServidor: (body: IntegracoesServidorRef, options?: RequestOptions) =>
    request<IntegracoesServidorMcp>("POST", "/api/v1/integracoes/servidores/remover", body, options),
};

export interface NotifyNotification {
  id: string;
  title: string;
  body: string;
  link: string | null;
  action: string | null;
  /** Serviço que avisou (svc-...) */
  service: string;
  read: boolean;
  created_at: string;
}

export interface NotifyNotificationPage {
  items: NotifyNotification[];
  /** Itens que atendem ao filtro, somando todas as páginas */
  total: number;
  page: number;
  size: number;
  /** Total de páginas (0 quando não há itens) */
  pages: number;
}

export interface NotifyNotificationQuery {
  /** Página, a partir de 1 */
  page?: number;
  /** Itens por página (até 100) */
  size?: number;
  /** Ordem: "campo" (crescente) ou "-campo" (decrescente) */
  sort?: "created_at" | "-created_at" | null;
  /** Busca por palavras (início de palavra, sem acento) */
  q?: string | null;
  /** false: só os não lidos */
  read?: boolean | null;
}

export interface NotifyUnread {
  count: number;
}

export interface NotifyReadRequest {
  ids: string[];
}

export interface NotifyPreferences {
  /** Receber os avisos também por e-mail (os de segurança sempre chegam) */
  email: boolean;
}

/** svc-notify · /api/v1/notify */
export const notify = {
  /** GET /api/v1/notify/items · http · exige token */
  items: (query?: NotifyNotificationQuery, options?: RequestOptions) =>
    request<NotifyNotificationPage>("GET", withQuery("/api/v1/notify/items", query), undefined, options),
  /** GET /api/v1/notify/unread · http · exige token */
  unread: (options?: RequestOptions) =>
    request<NotifyUnread>("GET", "/api/v1/notify/unread", undefined, options),
  /** POST /api/v1/notify/read · http · exige token */
  read: (body: NotifyReadRequest, options?: RequestOptions) =>
    request<NotifyUnread>("POST", "/api/v1/notify/read", body, options),
  /** POST /api/v1/notify/read-all · http · exige token */
  readAll: (body: unknown, options?: RequestOptions) =>
    request<NotifyUnread>("POST", "/api/v1/notify/read-all", body, options),
  /** GET /api/v1/notify/preferences · http · exige token */
  preferences: (options?: RequestOptions) =>
    request<NotifyPreferences>("GET", "/api/v1/notify/preferences", undefined, options),
  /** POST /api/v1/notify/preferences · http · exige token */
  setPreferences: (body: NotifyPreferences, options?: RequestOptions) =>
    request<NotifyPreferences>("POST", "/api/v1/notify/preferences", body, options),
};

export interface PlansLimitState {
  /** Nome completo: <serviço>.<limite> */
  name: string;
  service: string;
  description: string;
  /** Valor sem plano (ou que o plano não cita); null: sem limite */
  default: number | null;
  /** Consumo somado no mês (true) ou total do que existe agora (false) */
  monthly: boolean;
  unit: string;
  currency: string | null;
  /** O que o plano permite (ou o default); null: sem limite */
  limit: number | null;
  /** Mensal: soma do mês. Total: o último total que o serviço informou */
  used: number;
}

export interface PlansModuleState {
  /** Nome do serviço, sem svc- (o mesmo de /api/v1/<nome>) */
  name: string;
  service: string;
  title: string;
  description: string;
  /** Grupo no menu */
  category: string;
  /** Módulo da plataforma: sempre ligado */
  core: boolean;
  /** Ligado quando o plano não diz nada (e para quem não tem plano) */
  default: boolean;
  /** Módulos sem os quais este não funciona */
  requires: string[];
  /** Ligado para a organização: ajuste dela, plano ou default, com os requires ligados */
  enabled: boolean;
}

export interface PlansPlan {
  slug: string;
  name: string;
  description: string;
  /** Preço por mês, informativo (a cobrança é do produto) */
  price: number;
  /** Moeda do preço */
  currency: "BRL" | "USD" | "EUR";
  /** Aparece para as organizações na comparação de planos */
  public: boolean;
  /** Plano de quem ainda não tem um atribuído */
  default: boolean;
  /** Limite → valor (null: sem limite); o que falta vale o default */
  limits: Record<string, number | null>;
  /** Módulo → incluído; o que falta vale o default do módulo */
  modules: Record<string, boolean>;
}

export interface PlansCurrent {
  /** Id da organização: quem administra a plataforma atribui o plano por ele */
  tenant: string;
  /** Plano em vigor (atribuído ou o padrão); null: sem plano */
  plan: PlansPlan | null;
  /** AAAA-MM, em UTC: o mês dos consumos */
  month: string;
  limits: PlansLimitState[];
  modules: PlansModuleState[];
  manages_platform: boolean;
}

export interface PlansPlanList {
  items: PlansPlan[];
  /** Slug do plano da organização ativa (null: sem plano) */
  current: string | null;
  /** Quem pede administra os planos da plataforma */
  manages_platform: boolean;
}

/** Os módulos da plataforma e se cada um está ligado para a organização ativa (o menu esconde os desligados). */
export interface PlansModuleList {
  items: PlansModuleState[];
}

export interface PlansCatalogLimit {
  /** Nome completo: <serviço>.<limite> */
  name: string;
  service: string;
  description: string;
  /** Valor sem plano (ou que o plano não cita); null: sem limite */
  default: number | null;
  /** Consumo somado no mês (true) ou total do que existe agora (false) */
  monthly: boolean;
  unit: string;
  currency: string | null;
}

export interface PlansCatalogModule {
  /** Nome do serviço, sem svc- (o mesmo de /api/v1/<nome>) */
  name: string;
  service: string;
  title: string;
  description: string;
  /** Grupo no menu */
  category: string;
  /** Módulo da plataforma: sempre ligado */
  core: boolean;
  /** Ligado quando o plano não diz nada (e para quem não tem plano) */
  default: boolean;
  /** Módulos sem os quais este não funciona */
  requires: string[];
}

/** O que os serviços declararam: os módulos (por categoria) e os limites. */
export interface PlansCatalog {
  modules: PlansCatalogModule[];
  limits: PlansCatalogLimit[];
}

export interface PlansPlanInput {
  /** Identificador curto e permanente (ex.: gratis, pro) */
  slug: string;
  name: string;
  description?: string;
  /** Preço por mês, informativo */
  price?: number;
  currency?: "BRL" | "USD" | "EUR";
  public?: boolean;
  default?: boolean;
  /** Limite → valor (null: sem limite) */
  limits?: Record<string, number | null>;
  /** Módulo → incluído (o que falta vale o default) */
  modules?: Record<string, boolean>;
}

export interface PlansPlanUpdate {
  slug: string;
  name?: string | null;
  description?: string | null;
  price?: number | null;
  currency?: "BRL" | "USD" | "EUR" | null;
  public?: boolean | null;
  default?: boolean | null;
  /** Substitui a lista inteira */
  limits?: Record<string, number | null> | null;
  /** Substitui a lista inteira */
  modules?: Record<string, boolean> | null;
}

export interface PlansPlanRef {
  slug: string;
}

export interface PlansAccount {
  tenant: string;
  tenant_name: string;
  /** Plano em vigor (atribuído ou o padrão); null: sem plano */
  plan: string | null;
  plan_name: string;
  /** O plano foi atribuído (false: vale o padrão) */
  assigned: boolean;
  /** Ajuste da organização além do plano: módulo → ligado */
  modules: Record<string, boolean>;
}

export interface PlansAccountRef {
  tenant: string;
}

export interface PlansAssignInput {
  /** Id da organização (aparece para ela na tela Plano) */
  tenant: string;
  plan: string;
  /** Ajuste da organização: módulo → ligado, além do plano. null: mantém o ajuste; {}: só o plano */
  modules?: Record<string, boolean> | null;
}

/** Consumo ou total que mudou (também vai ao vivo para a tela da organização). */
export interface PlansUsageChanged {
  name: string;
  used: number;
}

/** svc-plans · /api/v1/plans */
export const plans = {
  /** GET /api/v1/plans/current · http · exige token */
  current: (options?: RequestOptions) =>
    request<PlansCurrent>("GET", "/api/v1/plans/current", undefined, options),
  /** GET /api/v1/plans/plans · http · exige token */
  list: (options?: RequestOptions) =>
    request<PlansPlanList>("GET", "/api/v1/plans/plans", undefined, options),
  /** GET /api/v1/plans/modules · http · exige token */
  modules: (options?: RequestOptions) =>
    request<PlansModuleList>("GET", "/api/v1/plans/modules", undefined, options),
  /** GET /api/v1/plans/catalog · http · exige token */
  catalog: (options?: RequestOptions) =>
    request<PlansCatalog>("GET", "/api/v1/plans/catalog", undefined, options),
  /** POST /api/v1/plans/plans · http · exige token */
  createPlan: (body: PlansPlanInput, options?: RequestOptions) =>
    request<PlansPlan>("POST", "/api/v1/plans/plans", body, options),
  /** POST /api/v1/plans/plans/update · http · exige token */
  updatePlan: (body: PlansPlanUpdate, options?: RequestOptions) =>
    request<PlansPlan>("POST", "/api/v1/plans/plans/update", body, options),
  /** POST /api/v1/plans/plans/remove · http · exige token */
  removePlan: (body: PlansPlanRef, options?: RequestOptions) =>
    request<PlansPlanList>("POST", "/api/v1/plans/plans/remove", body, options),
  /** GET /api/v1/plans/account · http · exige token */
  account: (query?: PlansAccountRef, options?: RequestOptions) =>
    request<PlansAccount>("GET", withQuery("/api/v1/plans/account", query), undefined, options),
  /** POST /api/v1/plans/assign · http · exige token */
  assign: (body: PlansAssignInput, options?: RequestOptions) =>
    request<PlansAccount>("POST", "/api/v1/plans/assign", body, options),
};

export interface ProcessosModeloProcesso {
  id: "contas-a-pagar" | "conciliacao-bancaria" | "faturamento-cobranca" | "fechamento-mes" | "gestao-contratos" | "publicacoes-processos" | "certidoes-negativas" | "admissao-colaborador" | "compras-cotacao" | "vencimentos-empresa" | "qualificacao-leads" | "proposta-comercial" | "reativacao-carteira";
  area: "financeiro" | "juridico" | "administrativo" | "vendas";
  titulo: string;
  resumo: string;
  gatilho: string;
  /** O que agentes e automações fazem sem ninguém */
  roda_sozinho: string;
  /** Quando uma pessoa entra (a exceção) */
  handoff: string;
  /** O que precisa estar conectado */
  integracoes: string[];
  /** O que, no perfil, indica que o processo serve */
  sinais: string[];
}

export interface ProcessosBiblioteca {
  itens: ProcessosModeloProcesso[];
}

export interface ProcessosPedidoAjuda {
  texto: string;
  por: string | null;
  em: string | null;
}

export interface ProcessosProcesso {
  id: string;
  /** Modelo da biblioteca; vazio num processo só da empresa */
  modelo: "contas-a-pagar" | "conciliacao-bancaria" | "faturamento-cobranca" | "fechamento-mes" | "gestao-contratos" | "publicacoes-processos" | "certidoes-negativas" | "admissao-colaborador" | "compras-cotacao" | "vencimentos-empresa" | "qualificacao-leads" | "proposta-comercial" | "reativacao-carteira" | null;
  area: "financeiro" | "juridico" | "administrativo" | "vendas";
  titulo: string;
  descricao: string;
  /** Por que o agente sugeriu (o que no briefing indica o processo) */
  motivo: string | null;
  origem: "sugestao" | "cliente";
  status: "sugerido" | "aceito" | "recusado";
  prioridade: "alta" | "media" | "baixa";
  /** Número da versão publicada (a que roda) */
  publicada: number | null;
  /** Pedido de ajuda ao staff em aberto no desenho */
  ajuda: ProcessosPedidoAjuda | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface ProcessosProcessoPage {
  items: ProcessosProcesso[];
  /** Itens que atendem ao filtro, somando todas as páginas */
  total: number;
  page: number;
  size: number;
  /** Total de páginas (0 quando não há itens) */
  pages: number;
}

export interface ProcessosProcessoQuery {
  /** Página, a partir de 1 */
  page?: number;
  /** Itens por página (até 100) */
  size?: number;
  /** Ordem: "campo" (crescente) ou "-campo" (decrescente) */
  sort?: "created_at" | "-created_at" | "titulo" | "-titulo" | "prioridade" | "-prioridade" | null;
  /** Busca por palavras (início de palavra, sem acento) */
  q?: string | null;
  status?: "sugerido" | "aceito" | "recusado" | null;
  area?: "financeiro" | "juridico" | "administrativo" | "vendas" | null;
}

export interface ProcessosResumo {
  sugeridos: number;
  aceitos: number;
  recusados: number;
  /** Aceitos com versão publicada (rodando no motor) */
  publicados: number;
}

export interface ProcessosEmpty {
}

export interface ProcessosDescoberta {
  /** Resumo do agente para o cliente */
  texto: string;
  /** Os sugeridos agora */
  processos: ProcessosProcesso[];
}

/** Um passo do agente enquanto trabalha (pedaço do stream). */
export interface ProcessosPassoAgente {
  ferramenta: string;
  texto: string;
  status: "running" | "done" | "failed";
}

export interface ProcessosDescricao {
  /** O processo, como o cliente explicaria a alguém */
  texto: string;
}

export interface ProcessosProcessoRef {
  id: string;
}

export interface ProcessosCatalogAction {
  /** <pacote>.<ação> */
  name: string;
  service: string;
  title: string;
  description: string;
  risk: "leitura" | "escrita" | "externa" | "irreversivel";
  connections: string[];
  /** Campos da saída (o que as condições podem usar) */
  output_fields: string[];
  example: Record<string, unknown>;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
}

export interface ProcessosCatalogoAcoes {
  itens: ProcessosCatalogAction[];
}

export interface ProcessosDesenhoRef {
  processo: string;
}

export interface ProcessosAlternative {
  /** <passo>.<campo> ou parametros.<nome> */
  campo: string;
  operador: "=" | "!=" | ">" | ">=" | "<" | "<=" | "verdadeiro" | "falso";
  /** Valor comparado; parametros.<nome> compara com um parâmetro */
  valor: string | number | boolean | null;
}

export interface ProcessosAvaliacao {
  ok: boolean;
  detalhes: string[];
}

/** Condição de um caminho que sai de uma decisão: campo, operador e valor (ou parametros.<nome>); com ou, basta uma delas valer (ex.: valor acima do limite ou fornecedor novo). */
export interface ProcessosCondition {
  /** <passo>.<campo> ou parametros.<nome> */
  campo: string;
  operador: "=" | "!=" | ">" | ">=" | "<" | "<=" | "verdadeiro" | "falso";
  /** Valor comparado; parametros.<nome> compara com um parâmetro */
  valor: string | number | boolean | null;
  /** Outras condições: o caminho vale se qualquer uma valer */
  ou: ProcessosAlternative[];
}

export interface ProcessosFlow {
  de: string;
  para: string;
  /** Só saindo de decisão; sem condição é o caminho padrão */
  condicao: ProcessosCondition | null;
}

export interface ProcessosFluxo {
  gatilho: ProcessosTrigger;
  passos: ProcessosStep[];
  ligacoes: ProcessosFlow[];
  parametros: Record<string, string | number | boolean>;
}

export interface ProcessosMensagemDesenho {
  id: string;
  papel: "cliente" | "agente" | "staff";
  /** Quem escreveu (cliente ou staff) */
  autor: string | null;
  texto: string;
  passos: string[];
  created_at: string | null;
}

/** O que o Camunda guardou na publicação. */
export interface ProcessosMotor {
  /** Id do processo BPMN no motor */
  processo: string;
  chave: string;
  versao: number;
  /** Impressão do BPMN implantado (publicar o mesmo BPMN não muda nada) */
  hash: string | null;
}

export interface ProcessosProblema {
  nivel: "erro" | "aviso";
  passo: string | null;
  texto: string;
}

/** Algo que o staff ensinou ao agente de um passo, ao resolver uma exceção. Entra no agente só depois de avaliada: com ela, o agente refaz o caso que a gerou e chega no que o staff fez. */
export interface ProcessosRegra {
  id: string;
  processo: string;
  passo: string;
  passo_nome: string;
  texto: string;
  /** A saída que o staff preencheu no caso que a gerou */
  esperado: Record<string, unknown>;
  status: "avaliando" | "ativa" | "reprovada" | "desativada";
  avaliacao: ProcessosAvaliacao | null;
  autor: string | null;
  created_at: string | null;
}

export interface ProcessosStep {
  /** Identificador curto em snake_case (a saída fica sob ele) */
  id: string;
  tipo: "acao" | "agente" | "tarefa" | "decisao" | "espera" | "fim";
  nome: string;
  /** acao: nome no catálogo (<pacote>.<ação>) */
  acao: string | null;
  /** agente: o que o agente faz neste passo */
  objetivo: string | null;
  /** agente: campos que o agente devolve */
  saidas: string[];
  /** agente: saída de exemplo para a simulação */
  exemplo: Record<string, string | number | boolean>;
  /** tarefa: quem decide */
  responsavel: "cliente" | "staff" | null;
  /** tarefa: o que a pessoa decide (a saída é aprovado) */
  pergunta: string | null;
  espera: "mensagem" | "tempo" | null;
  /** espera: mensagem que chega (ex.: banco.pago) */
  mensagem: string | null;
  /** espera: campo que identifica a execução */
  chave: string | null;
  /** espera tempo: quanto; tarefa e espera de mensagem: prazo */
  horas: number | null;
  /** acao e agente: caminho de handoff para o staff */
  excecao: boolean;
  /** agente: as saídas são lidas de um documento; cada uma precisa do trecho de onde saiu (ou de uma regra do staff), senão o passo vai para o staff */
  leitura: boolean;
  /** agente: um agente da organização (svc-agentes); sem ele, o da Cogniventure */
  agente_id: string | null;
  /** fim: como termina (ex.: pago, recusado) */
  resultado: string | null;
}

export interface ProcessosTrigger {
  tipo: "evento" | "agenda" | "manual";
  /** evento: mensagem que inicia */
  evento: string | null;
  /** agenda: cron (ex.: 0 8 * * *) */
  agenda: string | null;
  descricao: string | null;
}

export interface ProcessosVersao {
  id: string;
  processo: string;
  numero: number;
  status: "rascunho" | "revisao" | "publicada" | "arquivada";
  fluxo: ProcessosFluxo;
  /** Operações aplicadas neste rascunho */
  alteracoes: number;
  pode_desfazer: boolean;
  motor: ProcessosMotor | null;
  publicada_em: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface ProcessosVersaoResumo {
  numero: number;
  status: "rascunho" | "revisao" | "publicada" | "arquivada";
  motor_versao: number | null;
  publicada_em: string | null;
}

/** O desenho de um processo: a versão aberta (o rascunho, senão a publicada), o BPMN dela e a conversa. */
export interface ProcessosDesenho {
  processo: ProcessosProcesso;
  versao: ProcessosVersao;
  versoes: ProcessosVersaoResumo[];
  /** O BPMN da versão aberta, com o diagrama (o mesmo que vai ao motor) */
  bpmn: string;
  problemas: ProcessosProblema[];
  mensagens: ProcessosMensagemDesenho[];
  /** Ação irreversível ou conexão que a publicada não tinha: o staff revisa antes */
  exige_revisao: boolean;
  /** O que o rascunho muda na publicada (ou no fluxo de partida) */
  mudancas: string[];
  /** O que o staff ensinou aos passos deste processo */
  regras: ProcessosRegra[];
}

export interface ProcessosMensagemDesenhoIn {
  processo: string;
  texto: string;
}

export interface ProcessosSimulacaoIn {
  /** <passo>.<campo> → valor */
  valores?: Record<string, string | number | boolean>;
  /** Passos que caem na exceção (handoff) */
  excecoes?: string[];
  /** Tarefas em que a pessoa diz não */
  recusas?: string[];
  processo: string;
}

export interface ProcessosPassoSimulado {
  id: string;
  nome: string;
  tipo: string;
  /** O que aconteceu no passo (saída, condição avaliada) */
  nota: string;
}

export interface ProcessosSimulacao {
  /** Ids dos elementos percorridos no BPMN (passos e ligações) */
  caminho: string[];
  passos: ProcessosPassoSimulado[];
  /** Como terminou; vazio se parou antes */
  fim: string | null;
  problemas: string[];
}

export interface ProcessosExecucao {
  id: string;
  /** Execução no motor */
  instancia: string;
  processo: string;
  titulo: string;
  /** Versão nossa (a que estava publicada quando começou) */
  versao: number | null;
  motor_versao: number;
  status: "andamento" | "concluida" | "incidente" | "cancelada";
  /** Como terminou (o fim alcançado: pago, recusado...) */
  resultado: string | null;
  origem: "evento" | "manual" | "agenda";
  /** O que iniciou (ex.: o documento recebido) */
  resumo: string | null;
  passo_atual: string | null;
  passo_nome: string | null;
  aguardando: "cliente" | "staff" | "evento" | null;
  /** Exceções que foram para o staff (execução com handoff não conta na autonomia) */
  handoffs: number;
  marcos: ProcessosMarco[];
  /** O que cada passo devolveu */
  saidas: Record<string, Record<string, unknown>>;
  concluida_em: string | null;
  created_at: string | null;
  updated_at: string | null;
}

/** Um acontecimento na linha do tempo da execução. */
export interface ProcessosMarco {
  passo: string;
  nome: string;
  status: "iniciada" | "concluido" | "handoff" | "incidente" | "tentando" | "tarefa" | "resolvido" | "aguardando" | "fim";
  em: string;
  motivo: string | null;
  /** Quem resolveu (tarefa de pessoa) */
  por: string | null;
}

export interface ProcessosExecucaoPage {
  items: ProcessosExecucao[];
  /** Itens que atendem ao filtro, somando todas as páginas */
  total: number;
  page: number;
  size: number;
  /** Total de páginas (0 quando não há itens) */
  pages: number;
}

export interface ProcessosExecucaoQuery {
  /** Página, a partir de 1 */
  page?: number;
  /** Itens por página (até 100) */
  size?: number;
  /** Ordem: "campo" (crescente) ou "-campo" (decrescente) */
  sort?: "created_at" | "-created_at" | null;
  /** Busca por palavras (início de palavra, sem acento) */
  q?: string | null;
  status?: "andamento" | "concluida" | "incidente" | "cancelada" | null;
  processo?: string | null;
}

export interface ProcessosExecucaoDetalhe {
  execucao: ProcessosExecucao;
  /** O BPMN da versão em que a execução roda */
  bpmn: string;
  /** Elementos e ligações por onde passou (para pintar no diagrama) */
  caminho: string[];
  /** Onde está agora */
  atuais: string[];
}

export interface ProcessosExecucaoRef {
  id: string;
}

export interface ProcessosIniciar {
  processo: string;
  /** O que o gatilho traria (ex.: documento_id) */
  dados?: Record<string, string | number | boolean>;
}

/** Um campo que a pessoa preenche ao resolver uma exceção (a saída do passo que parou). */
export interface ProcessosCampo {
  nome: string;
  rotulo: string;
  tipo: "texto" | "numero" | "sim_nao";
  /** O que o agente ou a ação chegou a ver */
  valor: string | number | boolean | null;
}

export interface ProcessosItem {
  rotulo: string;
  valor: string;
}

export interface ProcessosTarefa {
  id: string;
  /** Tarefa no motor */
  chave: string;
  /** Id da execução */
  execucao: string;
  instancia: string;
  processo: string;
  /** Título do processo */
  titulo: string;
  /** Passo do fluxo a que a resposta pertence */
  passo: string;
  nome: string;
  tipo: "aprovacao" | "excecao";
  responsavel: "cliente" | "staff";
  pergunta: string;
  /** Exceção: por que o passo parou */
  motivo: string | null;
  contexto: ProcessosItem[];
  campos: ProcessosCampo[];
  documento_id: string | null;
  prazo: string | null;
  /** Exceção de agente: ao resolver, o staff pode ensinar uma regra */
  aprende: boolean;
  status: "aberta" | "concluida";
  resposta: Record<string, unknown>;
  concluida_por: string | null;
  concluida_em: string | null;
  created_at: string | null;
}

export interface ProcessosTarefaPage {
  items: ProcessosTarefa[];
  /** Itens que atendem ao filtro, somando todas as páginas */
  total: number;
  page: number;
  size: number;
  /** Total de páginas (0 quando não há itens) */
  pages: number;
}

export interface ProcessosTarefaQuery {
  /** Página, a partir de 1 */
  page?: number;
  /** Itens por página (até 100) */
  size?: number;
  /** Ordem: "campo" (crescente) ou "-campo" (decrescente) */
  sort?: "created_at" | "-created_at" | "prazo" | "-prazo" | null;
  /** Busca por palavras (início de palavra, sem acento) */
  q?: string | null;
  status?: "aberta" | "concluida" | null;
  responsavel?: "cliente" | "staff" | null;
  execucao?: string | null;
}

export interface ProcessosResposta {
  id: string;
  /** Aprovação: sim ou não */
  aprovado?: boolean | null;
  comentario?: string | null;
  /** Exceção: a saída do passo */
  dados?: Record<string, string | number | boolean | null>;
  /** Exceção de agente: o que o agente deve fazer da próxima vez (vira regra depois de avaliada) */
  regra?: string | null;
}

export interface ProcessosAcompanhamentoProcesso {
  processo: string;
  titulo: string;
  andamento: number;
  geral: ProcessosAutonomia;
  por_versao: ProcessosAutonomia[];
}

export interface ProcessosAutonomia {
  versao: number | null;
  concluidas: number;
  sem_handoff: number;
  /** Execuções sem handoff ÷ concluídas (0 a 1) */
  autonomia: number | null;
}

export interface ProcessosAcompanhamento {
  andamento: number;
  concluidas: number;
  incidentes: number;
  tarefas_cliente: number;
  tarefas_staff: number;
  atrasadas: number;
  autonomia: number | null;
  processos: ProcessosAcompanhamentoProcesso[];
}

export interface ProcessosRevisaoIn {
  processo: string;
  /** O que o staff deve olhar */
  mensagem?: string | null;
}

export interface ProcessosDevolucao {
  processo: string;
  motivo: string;
}

export interface ProcessosAjudaIn {
  processo: string;
  texto: string;
}

export interface ProcessosRegras {
  itens: ProcessosRegra[];
}

export interface ProcessosRegraQuery {
  processo?: string | null;
}

export interface ProcessosRegraRef {
  id: string;
}

export interface ProcessosProcessoMudou {
  id: string;
  action: "sugerido" | "aceito" | "recusado" | "descrito";
}

export interface ProcessosDesenhoMudou {
  processo: string;
  action: "alterado" | "mensagem" | "publicado" | "ajustado" | "descartado";
}

export interface ProcessosExecucaoMudou {
  id: string;
  action: "iniciada" | "mudou" | "concluida";
}

export interface ProcessosTarefaMudou {
  id: string;
  action: "criada" | "concluida";
}

export interface ProcessosRegraMudou {
  id: string;
  action: "criada" | "avaliada" | "desativada";
}

/** svc-processos · /api/v1/processos */
export const processos = {
  /** GET /api/v1/processos/biblioteca · http · exige token */
  biblioteca: (options?: RequestOptions) =>
    request<ProcessosBiblioteca>("GET", "/api/v1/processos/biblioteca", undefined, options),
  /** GET /api/v1/processos/processos · http · exige token */
  listar: (query?: ProcessosProcessoQuery, options?: RequestOptions) =>
    request<ProcessosProcessoPage>("GET", withQuery("/api/v1/processos/processos", query), undefined, options),
  /** GET /api/v1/processos/resumo · http · exige token */
  resumo: (options?: RequestOptions) =>
    request<ProcessosResumo>("GET", "/api/v1/processos/resumo", undefined, options),
  /** POST /api/v1/processos/descoberta · http · em pedaços (options.onDelta) · exige token */
  descoberta: (body: ProcessosEmpty, options?: StreamOptions<ProcessosPassoAgente>) =>
    stream<ProcessosPassoAgente, ProcessosDescoberta>("POST", "/api/v1/processos/descoberta", body, options),
  /** POST /api/v1/processos/descrever · http · exige token */
  descrever: (body: ProcessosDescricao, options?: RequestOptions) =>
    request<ProcessosProcesso>("POST", "/api/v1/processos/descrever", body, options),
  /** POST /api/v1/processos/processos/aceitar · http · exige token */
  aceitar: (body: ProcessosProcessoRef, options?: RequestOptions) =>
    request<ProcessosProcesso>("POST", "/api/v1/processos/processos/aceitar", body, options),
  /** POST /api/v1/processos/processos/recusar · http · exige token */
  recusar: (body: ProcessosProcessoRef, options?: RequestOptions) =>
    request<ProcessosProcesso>("POST", "/api/v1/processos/processos/recusar", body, options),
  /** GET /api/v1/processos/catalogo · http · exige token */
  catalogo: (options?: RequestOptions) =>
    request<ProcessosCatalogoAcoes>("GET", "/api/v1/processos/catalogo", undefined, options),
  /** POST /api/v1/processos/desenho/abrir · http · exige token */
  abrirDesenho: (body: ProcessosDesenhoRef, options?: RequestOptions) =>
    request<ProcessosDesenho>("POST", "/api/v1/processos/desenho/abrir", body, options),
  /** POST /api/v1/processos/desenho/mensagem · http · em pedaços (options.onDelta) · exige token */
  mensagemDesenho: (body: ProcessosMensagemDesenhoIn, options?: StreamOptions<ProcessosPassoAgente>) =>
    stream<ProcessosPassoAgente, ProcessosDesenho>("POST", "/api/v1/processos/desenho/mensagem", body, options),
  /** POST /api/v1/processos/desenho/simular · http · exige token */
  simular: (body: ProcessosSimulacaoIn, options?: RequestOptions) =>
    request<ProcessosSimulacao>("POST", "/api/v1/processos/desenho/simular", body, options),
  /** POST /api/v1/processos/desenho/desfazer · http · exige token */
  desfazer: (body: ProcessosDesenhoRef, options?: RequestOptions) =>
    request<ProcessosDesenho>("POST", "/api/v1/processos/desenho/desfazer", body, options),
  /** POST /api/v1/processos/desenho/publicar · http · exige token */
  publicar: (body: ProcessosDesenhoRef, options?: RequestOptions) =>
    request<ProcessosDesenho>("POST", "/api/v1/processos/desenho/publicar", body, options),
  /** POST /api/v1/processos/desenho/ajustar · http · exige token */
  ajustar: (body: ProcessosDesenhoRef, options?: RequestOptions) =>
    request<ProcessosDesenho>("POST", "/api/v1/processos/desenho/ajustar", body, options),
  /** POST /api/v1/processos/desenho/descartar · http · exige token */
  descartar: (body: ProcessosDesenhoRef, options?: RequestOptions) =>
    request<ProcessosDesenho>("POST", "/api/v1/processos/desenho/descartar", body, options),
  /** GET /api/v1/processos/execucoes · http · exige token */
  execucoes: (query?: ProcessosExecucaoQuery, options?: RequestOptions) =>
    request<ProcessosExecucaoPage>("GET", withQuery("/api/v1/processos/execucoes", query), undefined, options),
  /** GET /api/v1/processos/execucoes/item · http · exige token */
  execucao: (query?: ProcessosExecucaoRef, options?: RequestOptions) =>
    request<ProcessosExecucaoDetalhe>("GET", withQuery("/api/v1/processos/execucoes/item", query), undefined, options),
  /** POST /api/v1/processos/execucoes/iniciar · http · exige token */
  iniciar: (body: ProcessosIniciar, options?: RequestOptions) =>
    request<ProcessosExecucao>("POST", "/api/v1/processos/execucoes/iniciar", body, options),
  /** GET /api/v1/processos/tarefas · http · exige token */
  tarefas: (query?: ProcessosTarefaQuery, options?: RequestOptions) =>
    request<ProcessosTarefaPage>("GET", withQuery("/api/v1/processos/tarefas", query), undefined, options),
  /** POST /api/v1/processos/tarefas/responder · http · exige token */
  responder: (body: ProcessosResposta, options?: RequestOptions) =>
    request<ProcessosTarefa>("POST", "/api/v1/processos/tarefas/responder", body, options),
  /** GET /api/v1/processos/acompanhamento · http · exige token */
  acompanhamento: (options?: RequestOptions) =>
    request<ProcessosAcompanhamento>("GET", "/api/v1/processos/acompanhamento", undefined, options),
  /** POST /api/v1/processos/desenho/revisao · http · exige token */
  pedirRevisao: (body: ProcessosRevisaoIn, options?: RequestOptions) =>
    request<ProcessosDesenho>("POST", "/api/v1/processos/desenho/revisao", body, options),
  /** POST /api/v1/processos/desenho/aprovar · http · exige token */
  aprovarRevisao: (body: ProcessosDesenhoRef, options?: RequestOptions) =>
    request<ProcessosDesenho>("POST", "/api/v1/processos/desenho/aprovar", body, options),
  /** POST /api/v1/processos/desenho/devolver · http · exige token */
  devolver: (body: ProcessosDevolucao, options?: RequestOptions) =>
    request<ProcessosDesenho>("POST", "/api/v1/processos/desenho/devolver", body, options),
  /** POST /api/v1/processos/desenho/ajuda · http · exige token */
  pedirAjuda: (body: ProcessosAjudaIn, options?: RequestOptions) =>
    request<ProcessosDesenho>("POST", "/api/v1/processos/desenho/ajuda", body, options),
  /** POST /api/v1/processos/desenho/ajuda/concluir · http · exige token */
  concluirAjuda: (body: ProcessosDesenhoRef, options?: RequestOptions) =>
    request<ProcessosDesenho>("POST", "/api/v1/processos/desenho/ajuda/concluir", body, options),
  /** GET /api/v1/processos/regras · http · exige token */
  regras: (query?: ProcessosRegraQuery, options?: RequestOptions) =>
    request<ProcessosRegras>("GET", withQuery("/api/v1/processos/regras", query), undefined, options),
  /** POST /api/v1/processos/regras/desativar · http · exige token */
  desativarRegra: (body: ProcessosRegraRef, options?: RequestOptions) =>
    request<ProcessosRegra>("POST", "/api/v1/processos/regras/desativar", body, options),
};

export interface StaffResumo {
  /** Quem pergunta é da equipe da Cogniventure */
  staff: boolean;
  gestor: boolean;
  excecoes: number;
  atrasadas: number;
  escaladas: number;
  revisoes: number;
  ajudas: number;
  organizacoes: number;
}

export interface StaffOrganizacao {
  id: string;
  name: string;
  created_at: string | null;
}

export interface StaffOrganizacoes {
  items: StaffOrganizacao[];
}

export interface StaffCarteira {
  id: string;
  /** Id da pessoa do staff */
  pessoa: string;
  organizacao: string;
  organizacao_nome: string;
  created_at: string | null;
}

export interface StaffCarteiras {
  itens: StaffCarteira[];
}

export interface StaffNovaCarteira {
  pessoa: string;
  organizacao: string;
}

export interface StaffCarteiraRef {
  id: string;
}

export interface StaffSaude {
  organizacao: string;
  nome: string;
  andamento: number | null;
  concluidas: number | null;
  incidentes: number | null;
  autonomia: number | null;
  /** Exceções abertas na fila */
  excecoes: number;
  revisoes: number;
  ajudas: number;
  /** Falso quando a organização não respondeu agora */
  disponivel: boolean;
}

export interface StaffMinhaCarteira {
  gestor: boolean;
  itens: StaffSaude[];
}

export interface StaffItemFila {
  id: string;
  organizacao: string;
  organizacao_nome: string;
  tipo: "excecao" | "revisao" | "ajuda";
  ref: string;
  titulo: string;
  detalhe: string | null;
  prazo: string | null;
  status: "aberta" | "concluida";
  /** Onde resolver, na tela da organização (entre nela antes) */
  link: string;
  assumida_por: string | null;
  atribuida_a: string | null;
  /** Passou do prazo sem ninguém assumir: subiu para o gestor da carteira */
  escalada: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface StaffFilaPage {
  items: StaffItemFila[];
  /** Itens que atendem ao filtro, somando todas as páginas */
  total: number;
  page: number;
  size: number;
  /** Total de páginas (0 quando não há itens) */
  pages: number;
}

export interface StaffFilaQuery {
  /** Página, a partir de 1 */
  page?: number;
  /** Itens por página (até 100) */
  size?: number;
  /** Ordem: "campo" (crescente) ou "-campo" (decrescente) */
  sort?: "prazo" | "-prazo" | "created_at" | "-created_at" | null;
  /** Busca por palavras (início de palavra, sem acento) */
  q?: string | null;
  tipo?: "excecao" | "revisao" | "ajuda" | null;
  status?: "aberta" | "concluida" | null;
  escalada?: boolean | null;
  /** Gestor: a fila de todas as carteiras (não é filtro do banco) */
  todas?: boolean | null;
  organizacao?: string[] | null;
}

export interface StaffItemRef {
  id: string;
}

export interface StaffAtribuicao {
  id: string;
  pessoa: string;
}

export interface StaffFilaMudou {
  id: string;
  action: "chegou" | "mudou" | "escalada";
}

export interface StaffCarteiraMudou {
  id: string;
  action: "atribuida" | "removida";
}

/** svc-staff · /api/v1/staff */
export const staff = {
  /** GET /api/v1/staff/resumo · http · exige token */
  resumo: (options?: RequestOptions) =>
    request<StaffResumo>("GET", "/api/v1/staff/resumo", undefined, options),
  /** GET /api/v1/staff/organizacoes · http · exige token */
  organizacoes: (options?: RequestOptions) =>
    request<StaffOrganizacoes>("GET", "/api/v1/staff/organizacoes", undefined, options),
  /** GET /api/v1/staff/carteiras · http · exige token */
  carteiras: (options?: RequestOptions) =>
    request<StaffCarteiras>("GET", "/api/v1/staff/carteiras", undefined, options),
  /** POST /api/v1/staff/carteiras · http · exige token */
  atribuirCarteira: (body: StaffNovaCarteira, options?: RequestOptions) =>
    request<StaffCarteira>("POST", "/api/v1/staff/carteiras", body, options),
  /** POST /api/v1/staff/carteiras/remover · http · exige token */
  removerCarteira: (body: StaffCarteiraRef, options?: RequestOptions) =>
    request<StaffCarteira>("POST", "/api/v1/staff/carteiras/remover", body, options),
  /** GET /api/v1/staff/carteira · http · exige token */
  carteira: (options?: RequestOptions) =>
    request<StaffMinhaCarteira>("GET", "/api/v1/staff/carteira", undefined, options),
  /** GET /api/v1/staff/fila · http · exige token */
  fila: (query?: StaffFilaQuery, options?: RequestOptions) =>
    request<StaffFilaPage>("GET", withQuery("/api/v1/staff/fila", query), undefined, options),
  /** POST /api/v1/staff/fila/assumir · http · exige token */
  assumir: (body: StaffItemRef, options?: RequestOptions) =>
    request<StaffItemFila>("POST", "/api/v1/staff/fila/assumir", body, options),
  /** POST /api/v1/staff/fila/atribuir · http · exige token */
  atribuir: (body: StaffAtribuicao, options?: RequestOptions) =>
    request<StaffItemFila>("POST", "/api/v1/staff/fila/atribuir", body, options),
};

export interface WebhooksEndpoint {
  id: string;
  url: string;
  description: string;
  /** Eventos inscritos; ["*"] para todos */
  events: string[];
  enabled: boolean;
  /** Entregas seguidas sem sucesso */
  failures: number;
  disabled_reason: string | null;
  created_at: string;
}

export interface WebhooksEndpointList {
  items: WebhooksEndpoint[];
}

export interface WebhooksEndpointInput {
  /** Endereço que recebe os eventos (https) */
  url: string;
  description?: string;
  /** Eventos, ou ["*"] para todos */
  events: string[];
}

export interface WebhooksEndpointSecret {
  endpoint: WebhooksEndpoint;
  /** Segredo de assinatura (whsec_...): aparece só agora */
  secret: string;
}

export interface WebhooksEndpointUpdate {
  id: string;
  url?: string | null;
  description?: string | null;
  events?: string[] | null;
  enabled?: boolean | null;
}

export interface WebhooksEndpointRef {
  id: string;
}

export interface WebhooksDelivery {
  id: string;
  endpoint: string;
  url: string;
  event: string;
  status: "pending" | "sent" | "failed" | "skipped";
  attempts: number;
  /** Código HTTP da última resposta */
  response_status: number | null;
  error: string | null;
  duration_ms: number | null;
  created_at: string;
  delivered_at: string | null;
}

export interface WebhooksDeliveryPage {
  items: WebhooksDelivery[];
  /** Itens que atendem ao filtro, somando todas as páginas */
  total: number;
  page: number;
  size: number;
  /** Total de páginas (0 quando não há itens) */
  pages: number;
}

export interface WebhooksDeliveryQuery {
  /** Página, a partir de 1 */
  page?: number;
  /** Itens por página (até 100) */
  size?: number;
  /** Ordem: "campo" (crescente) ou "-campo" (decrescente) */
  sort?: "created_at" | "-created_at" | null;
  /** Busca por palavras (início de palavra, sem acento) */
  q?: string | null;
  endpoint?: string | null;
  status?: "pending" | "sent" | "failed" | "skipped" | null;
  event?: string | null;
}

export interface WebhooksDeliveryRef {
  id: string;
}

export interface WebhooksCatalogEvent {
  /** Nome completo: <serviço>.<evento> */
  name: string;
  service: string;
  description: string;
  /** JSON Schema do data */
  payload_schema: Record<string, unknown>;
}

export interface WebhooksEventList {
  items: WebhooksCatalogEvent[];
}

export interface WebhooksDeliveryChanged {
  id: string;
  status: "pending" | "sent" | "failed" | "skipped";
}

/** svc-webhooks · /api/v1/webhooks */
export const webhooks = {
  /** GET /api/v1/webhooks/endpoints · http · exige token */
  endpoints: (options?: RequestOptions) =>
    request<WebhooksEndpointList>("GET", "/api/v1/webhooks/endpoints", undefined, options),
  /** POST /api/v1/webhooks/endpoints · http · exige token */
  createEndpoint: (body: WebhooksEndpointInput, options?: RequestOptions) =>
    request<WebhooksEndpointSecret>("POST", "/api/v1/webhooks/endpoints", body, options),
  /** POST /api/v1/webhooks/endpoints/update · http · exige token */
  updateEndpoint: (body: WebhooksEndpointUpdate, options?: RequestOptions) =>
    request<WebhooksEndpoint>("POST", "/api/v1/webhooks/endpoints/update", body, options),
  /** POST /api/v1/webhooks/endpoints/remove · http · exige token */
  removeEndpoint: (body: WebhooksEndpointRef, options?: RequestOptions) =>
    request<WebhooksEndpointList>("POST", "/api/v1/webhooks/endpoints/remove", body, options),
  /** POST /api/v1/webhooks/endpoints/rotate · http · exige token */
  rotateSecret: (body: WebhooksEndpointRef, options?: RequestOptions) =>
    request<WebhooksEndpointSecret>("POST", "/api/v1/webhooks/endpoints/rotate", body, options),
  /** POST /api/v1/webhooks/endpoints/test · http · exige token */
  testEndpoint: (body: WebhooksEndpointRef, options?: RequestOptions) =>
    request<WebhooksDelivery>("POST", "/api/v1/webhooks/endpoints/test", body, options),
  /** GET /api/v1/webhooks/deliveries · http · exige token */
  deliveries: (query?: WebhooksDeliveryQuery, options?: RequestOptions) =>
    request<WebhooksDeliveryPage>("GET", withQuery("/api/v1/webhooks/deliveries", query), undefined, options),
  /** POST /api/v1/webhooks/deliveries/retry · http · exige token */
  retryDelivery: (body: WebhooksDeliveryRef, options?: RequestOptions) =>
    request<WebhooksDelivery>("POST", "/api/v1/webhooks/deliveries/retry", body, options),
  /** GET /api/v1/webhooks/events · http · exige token */
  events: (options?: RequestOptions) =>
    request<WebhooksEventList>("GET", "/api/v1/webhooks/events", undefined, options),
};

/** Eventos ao vivo (live: dos manifestos): tópico → o que o evento carrega. Use com useLive/useLiveQuery. */
export interface LiveTopics {
  /** svc-agentes · bus.live("agentes.agentes", ...) */
  "agentes.agentes": AgentesAgenteMudou;
  /** svc-ai · bus.live("ai.uso", ...) */
  "ai.uso": AiRecorded;
  /** svc-conhecimento · bus.live("conhecimento.briefing", ...) */
  "conhecimento.briefing": ConhecimentoBriefingMudou;
  /** svc-conhecimento · bus.live("conhecimento.leituras", ...) */
  "conhecimento.leituras": ConhecimentoLeituraMudou;
  /** svc-conhecimento · cadastro itens (core/resources.py) */
  "conhecimento.itens": ResourceChanged;
  /** svc-financeiro · bus.live("financeiro.titulos", ...) */
  "financeiro.titulos": FinanceiroTituloMudou;
  /** svc-financeiro · cadastro fornecedores (core/resources.py) */
  "financeiro.fornecedores": ResourceChanged;
  /** svc-identity · bus.live("identity.membros", ...) */
  "identity.membros": IdentityMembersChanged;
  /** svc-identity · bus.live("identity.acesso", ...) */
  "identity.acesso": IdentityAccessChanged;
  /** svc-integracoes · bus.live("integracoes.conexoes", ...) */
  "integracoes.conexoes": IntegracoesConexaoMudou;
  /** svc-integracoes · bus.live("integracoes.documentos", ...) */
  "integracoes.documentos": IntegracoesDocumentoMudou;
  /** svc-integracoes · bus.live("integracoes.pagamentos", ...) */
  "integracoes.pagamentos": IntegracoesPagamentoMudou;
  /** svc-integracoes · bus.live("integracoes.servidores", ...) */
  "integracoes.servidores": IntegracoesServidorMudou;
  /** svc-notify · bus.live("notify.nova", ...) */
  "notify.nova": NotifyNotification;
  /** svc-plans · bus.live("plans.uso", ...) */
  "plans.uso": PlansUsageChanged;
  /** svc-processos · bus.live("processos.processos", ...) */
  "processos.processos": ProcessosProcessoMudou;
  /** svc-processos · bus.live("processos.desenho", ...) */
  "processos.desenho": ProcessosDesenhoMudou;
  /** svc-processos · bus.live("processos.execucoes", ...) */
  "processos.execucoes": ProcessosExecucaoMudou;
  /** svc-processos · bus.live("processos.tarefas", ...) */
  "processos.tarefas": ProcessosTarefaMudou;
  /** svc-processos · bus.live("processos.regras", ...) */
  "processos.regras": ProcessosRegraMudou;
  /** svc-staff · bus.live("staff.fila", ...) */
  "staff.fila": StaffFilaMudou;
  /** svc-staff · bus.live("staff.carteiras", ...) */
  "staff.carteiras": StaffCarteiraMudou;
  /** svc-webhooks · bus.live("webhooks.entrega", ...) */
  "webhooks.entrega": WebhooksDeliveryChanged;
}

/** Módulos (o MODULE de cada services/svc-<nome>/schemas.py): o meta.module das telas e os grupos do menu. */
export const appModules = {
  agentes: { title: "Agentes", description: "Agentes da empresa: instrução, ferramentas do catálogo, política e suíte de avaliação", category: "Sua empresa", core: false },
  ai: { title: "IA", description: "Modelos de IA, chaves e consumo", category: "Integrações", core: true },
  conhecimento: { title: "Conhecimento", description: "Briefing da empresa e a base de conhecimento que os agentes consultam", category: "Sua empresa", core: false },
  financeiro: { title: "Financeiro", description: "Pacote de ações financeiras do BPO: contas a pagar, conciliação, cobrança e fechamento", category: "Pacotes", core: false },
  identity: { title: "Pessoas e acesso", description: "Contas, organizações, membros e convites", category: "Organização", core: true },
  integracoes: { title: "Integrações", description: "Conexões da empresa com o mundo de fora: caixa de entrada de documentos, banco e servidores MCP", category: "Integrações", core: false },
  notify: { title: "Avisos", description: "Avisos na tela e por e-mail", category: "Organização", core: true },
  plans: { title: "Plano", description: "Plano, módulos e consumo da organização", category: "Organização", core: true },
  processos: { title: "Processos", description: "Os processos que a Cogniventure executa para a empresa: sugeridos, descritos, desenhados e publicados", category: "Sua empresa", core: false },
  staff: { title: "Staff", description: "Área da equipe da Cogniventure: carteira de clientes, exceções, revisões e pedidos de ajuda", category: "Cogniventure", core: false },
  webhooks: { title: "Webhooks", description: "Eventos para os sistemas da organização", category: "Integrações", core: true },
} as const;

/** Nome de um módulo: o do serviço, sem svc-. */
export type ModuleName = keyof typeof appModules;
