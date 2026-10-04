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

export interface AdministrativoNovaAdmissao {
  /** Quem foi contratado */
  nome: string;
  /** Para onde vai o pedido de documentos */
  email: string;
  cargo: string;
  salario?: number | null;
  /** Primeiro dia de trabalho */
  inicio?: string | null;
}

/** Colaboradores: um registro. */
export interface AdministrativoColaboradorItem {
  /** Id do registro */
  id: string;
  created_at: string | null;
  created_by: string | null;
  updated_at: string | null;
  updated_by: string | null;
  nome: string;
  email: string | null;
  cargo: string | null;
  salario: number | null;
  inicio: string | null;
  status: "admissao" | "ativo" | "desligado";
  exame_em: string | null;
  acessos: string | null;
}

export interface AdministrativoCotacao {
  fornecedor: string;
  valor: number;
  prazo_dias: number | null;
}

/** Uma requisição de compra: as cotações que chegaram, a escolhida e o pedido. */
export interface AdministrativoRequisicao {
  id: string;
  item: string;
  quantidade: number;
  categoria: string | null;
  observacao: string | null;
  status: "aberta" | "cotando" | "pedido" | "cancelada";
  cotacoes: AdministrativoCotacao[];
  melhor_fornecedor: string | null;
  melhor_valor: number | null;
  pedido_numero: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface AdministrativoRequisicaoPage {
  items: AdministrativoRequisicao[];
  /** Itens que atendem ao filtro, somando todas as páginas */
  total: number;
  page: number;
  size: number;
  /** Total de páginas (0 quando não há itens) */
  pages: number;
}

export interface AdministrativoRequisicaoQuery {
  /** Página, a partir de 1 */
  page?: number;
  /** Itens por página (até 100) */
  size?: number;
  /** Ordem: "campo" (crescente) ou "-campo" (decrescente) */
  sort?: "created_at" | "-created_at" | "item" | "-item" | null;
  /** Busca por palavras (início de palavra, sem acento) */
  q?: string | null;
  status?: "aberta" | "cotando" | "pedido" | "cancelada" | null;
}

export interface AdministrativoNovaRequisicao {
  /** O que comprar */
  item: string;
  quantidade: number;
  /** Para escolher os fornecedores que cotam */
  categoria?: string | null;
  observacao?: string | null;
}

export interface AdministrativoNovaCotacao {
  requisicao: string;
  fornecedor: string;
  /** Valor total da cotação, em reais */
  valor: number;
  /** Prazo de entrega em dias */
  prazo_dias?: number | null;
}

export interface AdministrativoRequisicaoMudou {
  id: string;
  action: "aberta" | "cotando" | "cotacao" | "pedido" | "cancelada";
}

export interface AdministrativoColaborador {
  nome: string;
  email?: string | null;
  cargo?: string | null;
  salario?: number | null;
  inicio?: string | null;
  status?: "admissao" | "ativo" | "desligado";
  exame_em?: string | null;
  acessos?: string | null;
}

/** Colaboradores: só os campos que mudam. */
export interface AdministrativoColaboradorUpdate {
  /** Id do registro */
  id: string;
  nome?: string | null;
  email?: string | null;
  cargo?: string | null;
  salario?: number | null;
  inicio?: string | null;
  status?: "admissao" | "ativo" | "desligado" | null;
  exame_em?: string | null;
  acessos?: string | null;
}

/** Colaboradores: página, busca, filtros e ordem pela URL. */
export interface AdministrativoColaboradorQuery {
  /** Página, a partir de 1 */
  page?: number;
  /** Itens por página (até 100) */
  size?: number;
  /** Ordem: "campo" (crescente) ou "-campo" (decrescente) */
  sort?: "nome" | "-nome" | "created_at" | "-created_at" | null;
  /** Busca por palavras (início de palavra, sem acento) */
  q?: string | null;
  status?: "admissao" | "ativo" | "desligado" | null;
}

export interface AdministrativoColaboradorPage {
  items: AdministrativoColaboradorItem[];
  /** Itens que atendem ao filtro, somando todas as páginas */
  total: number;
  page: number;
  size: number;
  /** Total de páginas (0 quando não há itens) */
  pages: number;
}

export interface AdministrativoFornecedorCompra {
  nome: string;
  /** Para onde vão os pedidos de cotação e de compra */
  email?: string | null;
  /** Ex.: embalagens, limpeza, insumos */
  categoria?: string | null;
}

/** Fornecedores de compras: só os campos que mudam. */
export interface AdministrativoFornecedorCompraUpdate {
  /** Id do registro */
  id: string;
  nome?: string | null;
  /** Para onde vão os pedidos de cotação e de compra */
  email?: string | null;
  /** Ex.: embalagens, limpeza, insumos */
  categoria?: string | null;
}

/** Fornecedores de compras: página, busca, filtros e ordem pela URL. */
export interface AdministrativoFornecedorCompraQuery {
  /** Página, a partir de 1 */
  page?: number;
  /** Itens por página (até 100) */
  size?: number;
  /** Ordem: "campo" (crescente) ou "-campo" (decrescente) */
  sort?: "nome" | "-nome" | "created_at" | "-created_at" | null;
  /** Busca por palavras (início de palavra, sem acento) */
  q?: string | null;
}

/** Fornecedores de compras: um registro. */
export interface AdministrativoFornecedorCompraItem {
  /** Id do registro */
  id: string;
  created_at: string | null;
  created_by: string | null;
  updated_at: string | null;
  updated_by: string | null;
  nome: string;
  /** Para onde vão os pedidos de cotação e de compra */
  email: string | null;
  /** Ex.: embalagens, limpeza, insumos */
  categoria: string | null;
}

export interface AdministrativoFornecedorCompraPage {
  items: AdministrativoFornecedorCompraItem[];
  /** Itens que atendem ao filtro, somando todas as páginas */
  total: number;
  page: number;
  size: number;
  /** Total de páginas (0 quando não há itens) */
  pages: number;
}

export interface AdministrativoVencimento {
  nome: string;
  tipo?: "alvara" | "licenca" | "avcb" | "seguro" | "contrato_servico" | "outro";
  vence_em: string;
  exige_vistoria?: boolean;
  /** Quando a empresa foi avisada da renovação */
  avisado_em?: string | null;
}

/** Vencimentos: só os campos que mudam. */
export interface AdministrativoVencimentoUpdate {
  /** Id do registro */
  id: string;
  nome?: string | null;
  tipo?: "alvara" | "licenca" | "avcb" | "seguro" | "contrato_servico" | "outro" | null;
  vence_em?: string | null;
  exige_vistoria?: boolean | null;
  /** Quando a empresa foi avisada da renovação */
  avisado_em?: string | null;
}

/** Vencimentos: página, busca, filtros e ordem pela URL. */
export interface AdministrativoVencimentoQuery {
  /** Página, a partir de 1 */
  page?: number;
  /** Itens por página (até 100) */
  size?: number;
  /** Ordem: "campo" (crescente) ou "-campo" (decrescente) */
  sort?: "vence_em" | "-vence_em" | "nome" | "-nome" | "created_at" | "-created_at" | null;
  /** Busca por palavras (início de palavra, sem acento) */
  q?: string | null;
  tipo?: "alvara" | "licenca" | "avcb" | "seguro" | "contrato_servico" | "outro" | null;
}

/** Vencimentos: um registro. */
export interface AdministrativoVencimentoItem {
  /** Id do registro */
  id: string;
  created_at: string | null;
  created_by: string | null;
  updated_at: string | null;
  updated_by: string | null;
  nome: string;
  tipo: "alvara" | "licenca" | "avcb" | "seguro" | "contrato_servico" | "outro";
  vence_em: string;
  exige_vistoria: boolean;
  /** Quando a empresa foi avisada da renovação */
  avisado_em: string | null;
}

export interface AdministrativoVencimentoPage {
  items: AdministrativoVencimentoItem[];
  /** Itens que atendem ao filtro, somando todas as páginas */
  total: number;
  page: number;
  size: number;
  /** Total de páginas (0 quando não há itens) */
  pages: number;
}

/** svc-administrativo · /api/v1/administrativo */
export const administrativo = {
  /** POST /api/v1/administrativo/admissoes · http · exige token */
  admitir: (body: AdministrativoNovaAdmissao, options?: RequestOptions) =>
    request<AdministrativoColaboradorItem>("POST", "/api/v1/administrativo/admissoes", body, options),
  /** GET /api/v1/administrativo/requisicoes · http · exige token */
  requisicoes: (query?: AdministrativoRequisicaoQuery, options?: RequestOptions) =>
    request<AdministrativoRequisicaoPage>("GET", withQuery("/api/v1/administrativo/requisicoes", query), undefined, options),
  /** POST /api/v1/administrativo/requisicoes · http · exige token */
  requisitar: (body: AdministrativoNovaRequisicao, options?: RequestOptions) =>
    request<AdministrativoRequisicao>("POST", "/api/v1/administrativo/requisicoes", body, options),
  /** POST /api/v1/administrativo/requisicoes/cotacao · http · exige token */
  registrarCotacao: (body: AdministrativoNovaCotacao, options?: RequestOptions) =>
    request<AdministrativoRequisicao>("POST", "/api/v1/administrativo/requisicoes/cotacao", body, options),
  /** Cadastro Colaboradores (core/resources.py) · /api/v1/administrativo/colaboradores · exige token */
  colaboradores: {
    /** GET /api/v1/administrativo/colaboradores · página, busca, filtros e ordem */
    list: (query?: AdministrativoColaboradorQuery, options?: RequestOptions) =>
      request<AdministrativoColaboradorPage>("GET", withQuery("/api/v1/administrativo/colaboradores", query), undefined, options),
    /** GET /api/v1/administrativo/colaboradores/item?id= */
    get: (query: ResourceRef, options?: RequestOptions) =>
      request<AdministrativoColaboradorItem>("GET", withQuery("/api/v1/administrativo/colaboradores/item", query), undefined, options),
    /** POST /api/v1/administrativo/colaboradores */
    create: (body: AdministrativoColaborador, options?: RequestOptions) =>
      request<AdministrativoColaboradorItem>("POST", "/api/v1/administrativo/colaboradores", body, options),
    /** POST /api/v1/administrativo/colaboradores/update · só os campos que vierem mudam */
    update: (body: AdministrativoColaboradorUpdate, options?: RequestOptions) =>
      request<AdministrativoColaboradorItem>("POST", "/api/v1/administrativo/colaboradores/update", body, options),
    /** POST /api/v1/administrativo/colaboradores/remove */
    remove: (body: ResourceRef, options?: RequestOptions) =>
      request<ResourceRemoved>("POST", "/api/v1/administrativo/colaboradores/remove", body, options),
    /** Campos, colunas e filtros: o que useResource e ResourceList usam para montar a tela. */
    meta: {"title": "Colaboradores", "live": "administrativo.colaboradores", "fields": [{"name": "nome", "label": "Nome", "kind": "text", "required": true}, {"name": "email", "label": "E-mail", "kind": "email", "required": false}, {"name": "cargo", "label": "Cargo", "kind": "text", "required": false}, {"name": "salario", "label": "Salário", "kind": "money", "required": false}, {"name": "inicio", "label": "Início", "kind": "date", "required": false}, {"name": "status", "label": "Situação", "kind": "select", "required": false, "options": [{"value": "admissao", "label": "Em admissão"}, {"value": "ativo", "label": "Ativo"}, {"value": "desligado", "label": "Desligado"}]}, {"name": "exame_em", "label": "Exame admissional", "kind": "datetime", "required": false}, {"name": "acessos", "label": "Acessos a criar", "kind": "textarea", "required": false}], "columns": [{"key": "nome", "header": "Nome", "kind": "text", "sort": "nome"}, {"key": "email", "header": "E-mail", "kind": "email"}, {"key": "cargo", "header": "Cargo", "kind": "text"}, {"key": "salario", "header": "Salário", "kind": "money"}, {"key": "inicio", "header": "Início", "kind": "date"}], "filters": [{"name": "status", "label": "Situação", "options": [{"value": "admissao", "label": "Em admissão"}, {"value": "ativo", "label": "Ativo"}, {"value": "desligado", "label": "Desligado"}]}], "search": "nome, cargo"} satisfies ResourceMeta,
  },
  /** Cadastro Fornecedores de compras (core/resources.py) · /api/v1/administrativo/fornecedores · exige token */
  fornecedores: {
    /** GET /api/v1/administrativo/fornecedores · página, busca, filtros e ordem */
    list: (query?: AdministrativoFornecedorCompraQuery, options?: RequestOptions) =>
      request<AdministrativoFornecedorCompraPage>("GET", withQuery("/api/v1/administrativo/fornecedores", query), undefined, options),
    /** GET /api/v1/administrativo/fornecedores/item?id= */
    get: (query: ResourceRef, options?: RequestOptions) =>
      request<AdministrativoFornecedorCompraItem>("GET", withQuery("/api/v1/administrativo/fornecedores/item", query), undefined, options),
    /** POST /api/v1/administrativo/fornecedores */
    create: (body: AdministrativoFornecedorCompra, options?: RequestOptions) =>
      request<AdministrativoFornecedorCompraItem>("POST", "/api/v1/administrativo/fornecedores", body, options),
    /** POST /api/v1/administrativo/fornecedores/update · só os campos que vierem mudam */
    update: (body: AdministrativoFornecedorCompraUpdate, options?: RequestOptions) =>
      request<AdministrativoFornecedorCompraItem>("POST", "/api/v1/administrativo/fornecedores/update", body, options),
    /** POST /api/v1/administrativo/fornecedores/remove */
    remove: (body: ResourceRef, options?: RequestOptions) =>
      request<ResourceRemoved>("POST", "/api/v1/administrativo/fornecedores/remove", body, options),
    /** Campos, colunas e filtros: o que useResource e ResourceList usam para montar a tela. */
    meta: {"title": "Fornecedores de compras", "live": "administrativo.fornecedores", "fields": [{"name": "nome", "label": "Nome", "kind": "text", "required": true}, {"name": "email", "label": "E-mail", "kind": "email", "required": false, "hint": "Para onde vão os pedidos de cotação e de compra"}, {"name": "categoria", "label": "Categoria", "kind": "text", "required": false, "hint": "Ex.: embalagens, limpeza, insumos"}], "columns": [{"key": "nome", "header": "Nome", "kind": "text", "sort": "nome"}, {"key": "email", "header": "E-mail", "kind": "email"}, {"key": "categoria", "header": "Categoria", "kind": "text"}], "filters": [], "search": "nome, categoria"} satisfies ResourceMeta,
  },
  /** Cadastro Vencimentos (core/resources.py) · /api/v1/administrativo/vencimentos · exige token */
  vencimentos: {
    /** GET /api/v1/administrativo/vencimentos · página, busca, filtros e ordem */
    list: (query?: AdministrativoVencimentoQuery, options?: RequestOptions) =>
      request<AdministrativoVencimentoPage>("GET", withQuery("/api/v1/administrativo/vencimentos", query), undefined, options),
    /** GET /api/v1/administrativo/vencimentos/item?id= */
    get: (query: ResourceRef, options?: RequestOptions) =>
      request<AdministrativoVencimentoItem>("GET", withQuery("/api/v1/administrativo/vencimentos/item", query), undefined, options),
    /** POST /api/v1/administrativo/vencimentos */
    create: (body: AdministrativoVencimento, options?: RequestOptions) =>
      request<AdministrativoVencimentoItem>("POST", "/api/v1/administrativo/vencimentos", body, options),
    /** POST /api/v1/administrativo/vencimentos/update · só os campos que vierem mudam */
    update: (body: AdministrativoVencimentoUpdate, options?: RequestOptions) =>
      request<AdministrativoVencimentoItem>("POST", "/api/v1/administrativo/vencimentos/update", body, options),
    /** POST /api/v1/administrativo/vencimentos/remove */
    remove: (body: ResourceRef, options?: RequestOptions) =>
      request<ResourceRemoved>("POST", "/api/v1/administrativo/vencimentos/remove", body, options),
    /** Campos, colunas e filtros: o que useResource e ResourceList usam para montar a tela. */
    meta: {"title": "Vencimentos", "live": "administrativo.vencimentos", "fields": [{"name": "nome", "label": "O que vence", "kind": "text", "required": true}, {"name": "tipo", "label": "Tipo", "kind": "select", "required": false, "options": [{"value": "alvara", "label": "Alvará"}, {"value": "licenca", "label": "Licença"}, {"value": "avcb", "label": "AVCB"}, {"value": "seguro", "label": "Seguro"}, {"value": "contrato_servico", "label": "Contrato de serviço"}, {"value": "outro", "label": "Outro"}]}, {"name": "vence_em", "label": "Vence em", "kind": "date", "required": true}, {"name": "exige_vistoria", "label": "Exige vistoria ou presença", "kind": "boolean", "required": false, "options": [{"value": "true", "label": "Sim"}, {"value": "false", "label": "Não"}]}, {"name": "avisado_em", "label": "Avisado em", "kind": "date", "required": false, "hint": "Quando a empresa foi avisada da renovação"}], "columns": [{"key": "nome", "header": "O que vence", "kind": "text", "sort": "nome"}, {"key": "tipo", "header": "Tipo", "kind": "select"}, {"key": "vence_em", "header": "Vence em", "kind": "date", "sort": "vence_em"}, {"key": "exige_vistoria", "header": "Exige vistoria ou presença", "kind": "boolean"}, {"key": "avisado_em", "header": "Avisado em", "kind": "date"}], "filters": [{"name": "tipo", "label": "Tipo", "options": [{"value": "alvara", "label": "Alvará"}, {"value": "licenca", "label": "Licença"}, {"value": "avcb", "label": "AVCB"}, {"value": "seguro", "label": "Seguro"}, {"value": "contrato_servico", "label": "Contrato de serviço"}, {"value": "outro", "label": "Outro"}]}], "search": "o que vence"} satisfies ResourceMeta,
  },
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

export interface AtendimentoResumo {
  /** Falso na organização da Cogniventure e para quem só é operador ali */
  pode_pedir: boolean;
  abertos: number;
  respondidos: number;
}

export interface AtendimentoMensagem {
  papel: "cliente" | "staff";
  /** Id de quem escreveu */
  autor: string;
  autor_nome: string | null;
  texto: string;
  em: string;
}

export interface AtendimentoPedido {
  id: string;
  /** As primeiras palavras do pedido */
  assunto: string;
  status: "aberto" | "respondido" | "encerrado";
  /** A tela de onde a pessoa pediu ajuda */
  pagina: string | null;
  autor: string;
  autor_nome: string | null;
  mensagens: AtendimentoMensagem[];
  /** Até quando o staff responde (4 h depois da última mensagem do cliente) */
  prazo: string | null;
  respondido_em: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface AtendimentoPedidoPage {
  items: AtendimentoPedido[];
  /** Itens que atendem ao filtro, somando todas as páginas */
  total: number;
  page: number;
  size: number;
  /** Total de páginas (0 quando não há itens) */
  pages: number;
}

export interface AtendimentoPedidoQuery {
  /** Página, a partir de 1 */
  page?: number;
  /** Itens por página (até 100) */
  size?: number;
  /** Ordem: "campo" (crescente) ou "-campo" (decrescente) */
  sort?: "created_at" | "-created_at" | "updated_at" | "-updated_at" | null;
  /** Busca por palavras (início de palavra, sem acento) */
  q?: string | null;
  status?: "aberto" | "respondido" | "encerrado" | null;
  /** Só os pedidos desta pessoa (o membro vê sempre só os seus) */
  autor?: string | null;
}

export interface AtendimentoPedidoRef {
  id: string;
}

export interface AtendimentoNovoPedido {
  /** O que a pessoa precisa */
  texto: string;
  /** A tela de onde pediu (ex.: /processos/execucoes) */
  pagina?: string | null;
}

export interface AtendimentoMensagemNova {
  id: string;
  texto: string;
}

export interface AtendimentoPedidoMudou {
  id: string;
  action: "aberto" | "respondido" | "encerrado";
}

/** svc-atendimento · /api/v1/atendimento */
export const atendimento = {
  /** GET /api/v1/atendimento/resumo · http · exige token */
  resumo: (options?: RequestOptions) =>
    request<AtendimentoResumo>("GET", "/api/v1/atendimento/resumo", undefined, options),
  /** GET /api/v1/atendimento/pedidos · http · exige token */
  pedidos: (query?: AtendimentoPedidoQuery, options?: RequestOptions) =>
    request<AtendimentoPedidoPage>("GET", withQuery("/api/v1/atendimento/pedidos", query), undefined, options),
  /** GET /api/v1/atendimento/pedidos/item · http · exige token */
  pedido: (query?: AtendimentoPedidoRef, options?: RequestOptions) =>
    request<AtendimentoPedido>("GET", withQuery("/api/v1/atendimento/pedidos/item", query), undefined, options),
  /** POST /api/v1/atendimento/pedidos · http · exige token */
  abrir: (body: AtendimentoNovoPedido, options?: RequestOptions) =>
    request<AtendimentoPedido>("POST", "/api/v1/atendimento/pedidos", body, options),
  /** POST /api/v1/atendimento/pedidos/mensagem · http · exige token */
  escrever: (body: AtendimentoMensagemNova, options?: RequestOptions) =>
    request<AtendimentoPedido>("POST", "/api/v1/atendimento/pedidos/mensagem", body, options),
  /** POST /api/v1/atendimento/pedidos/encerrar · http · exige token */
  encerrar: (body: AtendimentoPedidoRef, options?: RequestOptions) =>
    request<AtendimentoPedido>("POST", "/api/v1/atendimento/pedidos/encerrar", body, options),
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
  /** Casou com o extrato do banco */
  conciliado: boolean;
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

/** Uma venda faturada pelo processo: nota, cobrança no banco, régua de lembretes e recebimento. */
export interface FinanceiroFatura {
  id: string;
  cliente: string;
  cnpj: string | null;
  email: string | null;
  descricao: string | null;
  valor: number;
  vencimento: string;
  nota_numero: string | null;
  cobranca_id: string | null;
  linha_digitavel: string | null;
  status: "aberta" | "cobrada" | "paga";
  /** Lembretes já enviados (D-3, D+1, D+7) */
  regua: string[];
  recebido_em: string | null;
  conciliada: boolean;
  proposta_id: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface FinanceiroFaturaPage {
  items: FinanceiroFatura[];
  /** Itens que atendem ao filtro, somando todas as páginas */
  total: number;
  page: number;
  size: number;
  /** Total de páginas (0 quando não há itens) */
  pages: number;
}

export interface FinanceiroFaturaQuery {
  /** Página, a partir de 1 */
  page?: number;
  /** Itens por página (até 100) */
  size?: number;
  /** Ordem: "campo" (crescente) ou "-campo" (decrescente) */
  sort?: "created_at" | "-created_at" | "vencimento" | "-vencimento" | "valor" | "-valor" | null;
  /** Busca por palavras (início de palavra, sem acento) */
  q?: string | null;
  status?: "aberta" | "cobrada" | "paga" | null;
}

export interface FinanceiroTituloMudou {
  id: string;
  action: "agendado" | "pago" | "conciliado";
}

export interface FinanceiroFaturaMudou {
  id: string;
  action: "aberta" | "cobrada" | "paga" | "lembrete";
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
  /** GET /api/v1/financeiro/faturas · http · exige token */
  faturas: (query?: FinanceiroFaturaQuery, options?: RequestOptions) =>
    request<FinanceiroFaturaPage>("GET", withQuery("/api/v1/financeiro/faturas", query), undefined, options),
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
  /** Cobranças emitidas e ainda não recebidas */
  cobrancas: number;
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

export interface IntegracoesCobranca {
  id: string;
  cobranca_id: string;
  valor: number;
  vencimento: string;
  pagador: string | null;
  descricao: string | null;
  linha_digitavel: string;
  status: "aberta" | "recebida";
  recebido_em: string | null;
  created_at: string | null;
}

export interface IntegracoesCobrancaPage {
  items: IntegracoesCobranca[];
  /** Itens que atendem ao filtro, somando todas as páginas */
  total: number;
  page: number;
  size: number;
  /** Total de páginas (0 quando não há itens) */
  pages: number;
}

export interface IntegracoesCobrancaQuery {
  /** Página, a partir de 1 */
  page?: number;
  /** Itens por página (até 100) */
  size?: number;
  /** Ordem: "campo" (crescente) ou "-campo" (decrescente) */
  sort?: "created_at" | "-created_at" | "vencimento" | "-vencimento" | "valor" | "-valor" | null;
  /** Busca por palavras (início de palavra, sem acento) */
  q?: string | null;
  status?: "aberta" | "recebida" | null;
}

export interface IntegracoesCobrancaRef {
  id: string;
}

export interface IntegracoesEnviado {
  id: string;
  para: string;
  assunto: string;
  de: string;
  created_at: string | null;
}

export interface IntegracoesEnviadoPage {
  items: IntegracoesEnviado[];
  /** Itens que atendem ao filtro, somando todas as páginas */
  total: number;
  page: number;
  size: number;
  /** Total de páginas (0 quando não há itens) */
  pages: number;
}

export interface IntegracoesEnviadoQuery {
  /** Página, a partir de 1 */
  page?: number;
  /** Itens por página (até 100) */
  size?: number;
  /** Ordem: "campo" (crescente) ou "-campo" (decrescente) */
  sort?: "created_at" | "-created_at" | null;
  /** Busca por palavras (início de palavra, sem acento) */
  q?: string | null;
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

export interface IntegracoesCobrancaMudou {
  id: string;
  action: "emitida" | "recebida";
}

export interface IntegracoesEnviadoMudou {
  id: string;
  action: "enviado";
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
  /** GET /api/v1/integracoes/cobrancas · http · exige token */
  cobrancas: (query?: IntegracoesCobrancaQuery, options?: RequestOptions) =>
    request<IntegracoesCobrancaPage>("GET", withQuery("/api/v1/integracoes/cobrancas", query), undefined, options),
  /** POST /api/v1/integracoes/cobrancas/confirmar · http · exige token */
  confirmarCobranca: (body: IntegracoesCobrancaRef, options?: RequestOptions) =>
    request<IntegracoesCobranca>("POST", "/api/v1/integracoes/cobrancas/confirmar", body, options),
  /** GET /api/v1/integracoes/enviados · http · exige token */
  enviados: (query?: IntegracoesEnviadoQuery, options?: RequestOptions) =>
    request<IntegracoesEnviadoPage>("GET", withQuery("/api/v1/integracoes/enviados", query), undefined, options),
};

export interface JuridicoContrato {
  parte: string;
  cnpj?: string | null;
  objeto: string;
  valor?: number | null;
  inicio?: string | null;
  /** A empresa é avisada 60 e 30 dias antes */
  fim?: string | null;
  reajuste_em?: string | null;
  status?: "vigente" | "encerrado";
  proposta_id?: string | null;
}

/** Contratos: só os campos que mudam. */
export interface JuridicoContratoUpdate {
  /** Id do registro */
  id: string;
  parte?: string | null;
  cnpj?: string | null;
  objeto?: string | null;
  valor?: number | null;
  inicio?: string | null;
  /** A empresa é avisada 60 e 30 dias antes */
  fim?: string | null;
  reajuste_em?: string | null;
  status?: "vigente" | "encerrado" | null;
  proposta_id?: string | null;
}

/** Contratos: página, busca, filtros e ordem pela URL. */
export interface JuridicoContratoQuery {
  /** Página, a partir de 1 */
  page?: number;
  /** Itens por página (até 100) */
  size?: number;
  /** Ordem: "campo" (crescente) ou "-campo" (decrescente) */
  sort?: "fim" | "-fim" | "parte" | "-parte" | "created_at" | "-created_at" | null;
  /** Busca por palavras (início de palavra, sem acento) */
  q?: string | null;
  status?: "vigente" | "encerrado" | null;
}

/** Contratos: um registro. */
export interface JuridicoContratoItem {
  /** Id do registro */
  id: string;
  created_at: string | null;
  created_by: string | null;
  updated_at: string | null;
  updated_by: string | null;
  parte: string;
  cnpj: string | null;
  objeto: string;
  valor: number | null;
  inicio: string | null;
  /** A empresa é avisada 60 e 30 dias antes */
  fim: string | null;
  reajuste_em: string | null;
  status: "vigente" | "encerrado";
  proposta_id: string | null;
}

export interface JuridicoContratoPage {
  items: JuridicoContratoItem[];
  /** Itens que atendem ao filtro, somando todas as páginas */
  total: number;
  page: number;
  size: number;
  /** Total de páginas (0 quando não há itens) */
  pages: number;
}

export interface JuridicoCertidao {
  referencia: string;
  /** Quantas vieram positivas (irregularidade) */
  positivas?: number;
  validade?: string | null;
  resumo?: string | null;
}

/** Certidões: só os campos que mudam. */
export interface JuridicoCertidaoUpdate {
  /** Id do registro */
  id: string;
  referencia?: string | null;
  /** Quantas vieram positivas (irregularidade) */
  positivas?: number | null;
  validade?: string | null;
  resumo?: string | null;
}

/** Certidões: página, busca, filtros e ordem pela URL. */
export interface JuridicoCertidaoQuery {
  /** Página, a partir de 1 */
  page?: number;
  /** Itens por página (até 100) */
  size?: number;
  /** Ordem: "campo" (crescente) ou "-campo" (decrescente) */
  sort?: "referencia" | "-referencia" | "validade" | "-validade" | "created_at" | "-created_at" | null;
  /** Busca por palavras (início de palavra, sem acento) */
  q?: string | null;
}

/** Certidões: um registro. */
export interface JuridicoCertidaoItem {
  /** Id do registro */
  id: string;
  created_at: string | null;
  created_by: string | null;
  updated_at: string | null;
  updated_by: string | null;
  referencia: string;
  /** Quantas vieram positivas (irregularidade) */
  positivas: number;
  validade: string | null;
  resumo: string | null;
}

export interface JuridicoCertidaoPage {
  items: JuridicoCertidaoItem[];
  /** Itens que atendem ao filtro, somando todas as páginas */
  total: number;
  page: number;
  size: number;
  /** Total de páginas (0 quando não há itens) */
  pages: number;
}

/** svc-juridico · /api/v1/juridico */
export const juridico = {
  /** Cadastro Contratos (core/resources.py) · /api/v1/juridico/contratos · exige token */
  contratos: {
    /** GET /api/v1/juridico/contratos · página, busca, filtros e ordem */
    list: (query?: JuridicoContratoQuery, options?: RequestOptions) =>
      request<JuridicoContratoPage>("GET", withQuery("/api/v1/juridico/contratos", query), undefined, options),
    /** GET /api/v1/juridico/contratos/item?id= */
    get: (query: ResourceRef, options?: RequestOptions) =>
      request<JuridicoContratoItem>("GET", withQuery("/api/v1/juridico/contratos/item", query), undefined, options),
    /** POST /api/v1/juridico/contratos */
    create: (body: JuridicoContrato, options?: RequestOptions) =>
      request<JuridicoContratoItem>("POST", "/api/v1/juridico/contratos", body, options),
    /** POST /api/v1/juridico/contratos/update · só os campos que vierem mudam */
    update: (body: JuridicoContratoUpdate, options?: RequestOptions) =>
      request<JuridicoContratoItem>("POST", "/api/v1/juridico/contratos/update", body, options),
    /** POST /api/v1/juridico/contratos/remove */
    remove: (body: ResourceRef, options?: RequestOptions) =>
      request<ResourceRemoved>("POST", "/api/v1/juridico/contratos/remove", body, options),
    /** Campos, colunas e filtros: o que useResource e ResourceList usam para montar a tela. */
    meta: {"title": "Contratos", "live": "juridico.contratos", "fields": [{"name": "parte", "label": "Outra parte", "kind": "text", "required": true}, {"name": "cnpj", "label": "CNPJ ou CPF", "kind": "text", "required": false}, {"name": "objeto", "label": "Objeto", "kind": "textarea", "required": true}, {"name": "valor", "label": "Valor", "kind": "money", "required": false}, {"name": "inicio", "label": "Início da vigência", "kind": "date", "required": false}, {"name": "fim", "label": "Fim da vigência", "kind": "date", "required": false, "hint": "A empresa é avisada 60 e 30 dias antes"}, {"name": "reajuste_em", "label": "Próximo reajuste", "kind": "date", "required": false}, {"name": "status", "label": "Situação", "kind": "select", "required": false, "options": [{"value": "vigente", "label": "Vigente"}, {"value": "encerrado", "label": "Encerrado"}]}, {"name": "proposta_id", "label": "Proposta de origem", "kind": "text", "required": false}], "columns": [{"key": "parte", "header": "Outra parte", "kind": "text", "sort": "parte"}, {"key": "valor", "header": "Valor", "kind": "money"}, {"key": "inicio", "header": "Início da vigência", "kind": "date"}, {"key": "fim", "header": "Fim da vigência", "kind": "date", "sort": "fim"}, {"key": "reajuste_em", "header": "Próximo reajuste", "kind": "date"}, {"key": "status", "header": "Situação", "kind": "select"}], "filters": [{"name": "status", "label": "Situação", "options": [{"value": "vigente", "label": "Vigente"}, {"value": "encerrado", "label": "Encerrado"}]}], "search": "outra parte, objeto"} satisfies ResourceMeta,
  },
  /** Cadastro Certidões (core/resources.py) · /api/v1/juridico/certidoes · exige token */
  certidoes: {
    /** GET /api/v1/juridico/certidoes · página, busca, filtros e ordem */
    list: (query?: JuridicoCertidaoQuery, options?: RequestOptions) =>
      request<JuridicoCertidaoPage>("GET", withQuery("/api/v1/juridico/certidoes", query), undefined, options),
    /** GET /api/v1/juridico/certidoes/item?id= */
    get: (query: ResourceRef, options?: RequestOptions) =>
      request<JuridicoCertidaoItem>("GET", withQuery("/api/v1/juridico/certidoes/item", query), undefined, options),
    /** POST /api/v1/juridico/certidoes */
    create: (body: JuridicoCertidao, options?: RequestOptions) =>
      request<JuridicoCertidaoItem>("POST", "/api/v1/juridico/certidoes", body, options),
    /** POST /api/v1/juridico/certidoes/update · só os campos que vierem mudam */
    update: (body: JuridicoCertidaoUpdate, options?: RequestOptions) =>
      request<JuridicoCertidaoItem>("POST", "/api/v1/juridico/certidoes/update", body, options),
    /** POST /api/v1/juridico/certidoes/remove */
    remove: (body: ResourceRef, options?: RequestOptions) =>
      request<ResourceRemoved>("POST", "/api/v1/juridico/certidoes/remove", body, options),
    /** Campos, colunas e filtros: o que useResource e ResourceList usam para montar a tela. */
    meta: {"title": "Certidões", "live": "juridico.certidoes", "fields": [{"name": "referencia", "label": "Mês (AAAA-MM)", "kind": "text", "required": true}, {"name": "positivas", "label": "Positivas", "kind": "number", "required": false, "hint": "Quantas vieram positivas (irregularidade)"}, {"name": "validade", "label": "Validade mais próxima", "kind": "date", "required": false}, {"name": "resumo", "label": "Resumo", "kind": "textarea", "required": false}], "columns": [{"key": "referencia", "header": "Mês (AAAA-MM)", "kind": "text", "sort": "referencia"}, {"key": "positivas", "header": "Positivas", "kind": "number"}, {"key": "validade", "header": "Validade mais próxima", "kind": "date", "sort": "validade"}], "filters": [], "search": null} satisfies ResourceMeta,
  },
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
  /** biblioteca: a empresa escolheu o modelo direto da biblioteca */
  origem: "sugestao" | "cliente" | "biblioteca";
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

export interface ProcessosAdicionarModelo {
  /** Modelo da biblioteca que a empresa quer executar */
  modelo: "contas-a-pagar" | "conciliacao-bancaria" | "faturamento-cobranca" | "fechamento-mes" | "gestao-contratos" | "publicacoes-processos" | "certidoes-negativas" | "admissao-colaborador" | "compras-cotacao" | "vencimentos-empresa" | "qualificacao-leads" | "proposta-comercial" | "reativacao-carteira";
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

/** Um processo da empresa ligado a este pela cadeia: começa quando este termina (com o resultado pedido). */
export interface ProcessosProcessoLigado {
  id: string;
  titulo: string;
  /** O fim deste processo que o inicia; vazio, qualquer um */
  resultado: string | null;
  publicada: number | null;
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
  /** paralelo: com vários caminhos saindo, abre ramos ao mesmo tempo; com vários chegando, espera todos */
  tipo: "acao" | "agente" | "tarefa" | "decisao" | "espera" | "paralelo" | "fim";
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
  tipo: "evento" | "agenda" | "manual" | "processo";
  /** evento: mensagem que inicia */
  evento: string | null;
  /** agenda: cron de 5 campos em UTC (ex.: 0 11 * * * = 8h em Brasília) */
  agenda: string | null;
  /** processo: o modelo da biblioteca (ou o id) do processo que, ao terminar, inicia este */
  processo: string | null;
  /** processo: o fim que ele precisa alcançar (ex.: aceita); vazio, qualquer um */
  resultado: string | null;
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
  /** Processos da empresa que este inicia ao terminar (a cadeia) */
  inicia: ProcessosProcessoLigado[];
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
  origem: "evento" | "manual" | "agenda" | "processo";
  /** O que iniciou (ex.: o documento recebido) */
  resumo: string | null;
  /** Execução do processo que iniciou esta (gatilho por outro processo) */
  pai: string | null;
  /** A primeira execução da cadeia: as execuções de um projeto têm o mesmo */
  projeto: string | null;
  /** Quantos processos antes deste na cadeia */
  nivel: number;
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
  projeto?: string | null;
}

/** Uma execução dentro de um projeto (a cadeia de processos que um começou). */
export interface ProcessosEtapaProjeto {
  id: string;
  processo: string;
  titulo: string;
  status: "andamento" | "concluida" | "incidente" | "cancelada";
  resultado: string | null;
  resumo: string | null;
  passo_nome: string | null;
  aguardando: "cliente" | "staff" | "evento" | null;
  handoffs: number;
  pai: string | null;
  created_at: string | null;
  concluida_em: string | null;
}

export interface ProcessosExecucaoDetalhe {
  execucao: ProcessosExecucao;
  /** O BPMN da versão em que a execução roda */
  bpmn: string;
  /** Elementos e ligações por onde passou (para pintar no diagrama) */
  caminho: string[];
  /** Onde está agora */
  atuais: string[];
  /** O projeto de que a execução faz parte (vazio fora de uma cadeia) */
  cadeia: ProcessosEtapaProjeto[];
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
  /** Processos aceitos pela empresa (a jornada: descoberta feita) */
  aceitos: number;
  /** Processos com versão publicada (a jornada: desenho feito) */
  publicados: number;
}

/** A cadeia que um processo começou (ex.: proposta aceita → contrato e faturamento), acompanhada como um projeto. */
export interface ProcessosProjeto {
  /** A execução que começou a cadeia */
  id: string;
  titulo: string;
  resumo: string | null;
  /** atencao: alguma execução com incidente */
  status: "andamento" | "concluido" | "atencao";
  etapas: ProcessosEtapaProjeto[];
  created_at: string | null;
}

export interface ProcessosProjetoPage {
  items: ProcessosProjeto[];
  /** Itens que atendem ao filtro, somando todas as páginas */
  total: number;
  page: number;
  size: number;
  /** Total de páginas (0 quando não há itens) */
  pages: number;
}

export interface ProcessosProjetoQuery {
  /** Página, a partir de 1 */
  page?: number;
  /** Itens por página (até 100) */
  size?: number;
  /** Ordem: "campo" (crescente) ou "-campo" (decrescente) */
  sort?: "created_at" | "-created_at" | null;
  /** Busca por palavras (início de palavra, sem acento) */
  q?: string | null;
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
  /** POST /api/v1/processos/processos/adicionar · http · exige token */
  adicionar: (body: ProcessosAdicionarModelo, options?: RequestOptions) =>
    request<ProcessosProcesso>("POST", "/api/v1/processos/processos/adicionar", body, options),
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
  /** GET /api/v1/processos/projetos · http · exige token */
  projetos: (query?: ProcessosProjetoQuery, options?: RequestOptions) =>
    request<ProcessosProjetoPage>("GET", withQuery("/api/v1/processos/projetos", query), undefined, options),
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
  pedidos: number;
  organizacoes: number;
}

export interface StaffCliente {
  organizacao: string;
  nome: string;
  created_at: string | null;
  /** Nome do plano (null: sem plano atribuído) */
  plano: string | null;
  /** Ids das pessoas do staff com o cliente na carteira */
  responsaveis: string[];
  dono: StaffDono | null;
  /** Convite de dono ainda não aceito */
  convite: StaffConvitePendente | null;
  /** Onde o cliente está na jornada (null: não deu para saber agora) */
  passo: "convite" | "briefing" | "descoberta" | "desenho" | "acompanhamento" | null;
  /** Último acesso de alguém do cliente (o staff não conta) */
  ultimo_acesso: string | null;
  andamento: number | null;
  autonomia: number | null;
}

export interface StaffConvitePendente {
  email: string | null;
  expires_at: string;
}

export interface StaffDono {
  name: string;
  email: string;
}

export interface StaffClientes {
  itens: StaffCliente[];
}

export interface StaffNovoCliente {
  /** Nome da empresa cliente */
  empresa: string;
  /** E-mail do dono, que recebe o convite */
  email: string;
  /** Slug do plano do cliente */
  plano: string;
  /** Quem do staff cuida dele (entra na carteira) */
  pessoa: string;
}

export interface StaffClienteRef {
  organizacao: string;
}

/** rpc.identity.organizacoes (contrato do svc-identity, repetido aqui por quem consome). */
export interface StaffOrganizacao {
  id: string;
  name: string;
  created_at: string | null;
  dono: StaffDono | null;
  convite: StaffConvitePendente | null;
  ultimo_acesso: string | null;
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
  /** Pedidos de ajuda (Falar com a Cogniventure) abertos */
  pedidos: number;
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
  tipo: "excecao" | "revisao" | "ajuda" | "pedido";
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
  concluida_em: string | null;
  /** Quem resolveu (pela fila ou na tela do cliente) */
  resolvida_por: string | null;
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
  tipo?: "excecao" | "revisao" | "ajuda" | "pedido" | null;
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

export interface StaffCampoTarefa {
  nome: string;
  rotulo: string;
  tipo: string;
  valor: unknown;
}

export interface StaffItemContexto {
  rotulo: string;
  valor: string;
}

export interface StaffMensagemPedido {
  papel: "cliente" | "staff";
  autor_nome: string | null;
  texto: string;
  em: string;
}

/** rpc.atendimento.pedido: o pedido de ajuda com a conversa. */
export interface StaffPedidoFila {
  id: string;
  assunto: string;
  status: string;
  pagina: string | null;
  mensagens: StaffMensagemPedido[];
}

/** rpc.processos.fila_revisao: a versão em revisão e o que ela muda. */
export interface StaffRevisaoFila {
  processo: string;
  titulo: string;
  numero: number;
  status: string;
  mudancas: string[];
}

/** rpc.processos.fila_tarefa: a exceção como o cartão da fila mostra. */
export interface StaffTarefaFila {
  id: string;
  titulo: string;
  nome: string;
  status: string;
  motivo: string | null;
  campos: StaffCampoTarefa[];
  contexto: StaffItemContexto[];
  aprende: boolean;
  prazo: string | null;
}

export interface StaffFilaDetalhe {
  item: StaffItemFila;
  tarefa: StaffTarefaFila | null;
  revisao: StaffRevisaoFila | null;
  pedido: StaffPedidoFila | null;
}

export interface StaffResolverExcecao {
  id: string;
  /** A saída do passo que parou */
  dados?: Record<string, string | number | boolean | null>;
  comentario?: string | null;
  /** Exceção de agente: vira regra depois de avaliada */
  regra?: string | null;
}

export interface StaffDecidirRevisao {
  id: string;
  aprovar: boolean;
  /** Ao devolver: o que precisa mudar */
  motivo?: string | null;
}

export interface StaffResponderPedido {
  id: string;
  texto: string;
}

export interface StaffNumeroLinha {
  /** Id da pessoa ou da organização */
  chave: string;
  /** Nome da organização (pessoa: a tela mostra pelo id) */
  nome: string | null;
  resolvidos: number;
  /** Resolvidos até o prazo (item sem prazo conta como no prazo) */
  no_prazo: number;
  /** Da chegada à resolução, em minutos */
  tempo_medio_min: number | null;
  abertos: number;
}

export interface StaffNumeros {
  desde: string;
  pessoas: StaffNumeroLinha[];
  clientes: StaffNumeroLinha[];
}

export interface StaffNumerosQuery {
  /** Os últimos N dias */
  dias?: number;
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
  /** GET /api/v1/staff/clientes · http · exige token */
  clientes: (options?: RequestOptions) =>
    request<StaffClientes>("GET", "/api/v1/staff/clientes", undefined, options),
  /** POST /api/v1/staff/clientes · http · exige token */
  novoCliente: (body: StaffNovoCliente, options?: RequestOptions) =>
    request<StaffCliente>("POST", "/api/v1/staff/clientes", body, options),
  /** POST /api/v1/staff/clientes/convite · http · exige token */
  convidarDono: (body: StaffClienteRef, options?: RequestOptions) =>
    request<StaffCliente>("POST", "/api/v1/staff/clientes/convite", body, options),
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
  /** GET /api/v1/staff/fila/detalhe · http · exige token */
  detalhe: (query?: StaffItemRef, options?: RequestOptions) =>
    request<StaffFilaDetalhe>("GET", withQuery("/api/v1/staff/fila/detalhe", query), undefined, options),
  /** POST /api/v1/staff/fila/resolver · http · exige token */
  resolver: (body: StaffResolverExcecao, options?: RequestOptions) =>
    request<StaffItemFila>("POST", "/api/v1/staff/fila/resolver", body, options),
  /** POST /api/v1/staff/fila/revisao · http · exige token */
  decidir: (body: StaffDecidirRevisao, options?: RequestOptions) =>
    request<StaffItemFila>("POST", "/api/v1/staff/fila/revisao", body, options),
  /** POST /api/v1/staff/fila/responder · http · exige token */
  responder: (body: StaffResponderPedido, options?: RequestOptions) =>
    request<StaffItemFila>("POST", "/api/v1/staff/fila/responder", body, options),
  /** GET /api/v1/staff/numeros · http · exige token */
  numeros: (query?: StaffNumerosQuery, options?: RequestOptions) =>
    request<StaffNumeros>("GET", withQuery("/api/v1/staff/numeros", query), undefined, options),
};

export interface VendasReceberLead {
  nome: string;
  email?: string | null;
  telefone?: string | null;
  origem?: "site" | "instagram" | "whatsapp" | "indicacao" | "outro";
  /** O que o lead escreveu */
  interesse?: string | null;
}

/** Leads: um registro. */
export interface VendasLeadItem {
  /** Id do registro */
  id: string;
  created_at: string | null;
  created_by: string | null;
  updated_at: string | null;
  updated_by: string | null;
  nome: string;
  email: string | null;
  telefone: string | null;
  origem: "site" | "instagram" | "whatsapp" | "indicacao" | "outro";
  interesse: string | null;
  status: "novo" | "qualificado" | "reuniao" | "nutricao" | "atendimento" | "cliente";
  reuniao_em: string | null;
}

/** Uma proposta comercial: do pedido à resposta do cliente. */
export interface VendasProposta {
  id: string;
  cliente: string;
  email: string | null;
  pedido: string;
  descricao: string | null;
  valor: number | null;
  desconto: number | null;
  validade: string | null;
  status: "pedida" | "montada" | "enviada" | "aceita" | "recusada";
  enviada_em: string | null;
  /** Follow-ups enviados (D3, D7) */
  follow_ups: string[];
  respondida_em: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface VendasPropostaPage {
  items: VendasProposta[];
  /** Itens que atendem ao filtro, somando todas as páginas */
  total: number;
  page: number;
  size: number;
  /** Total de páginas (0 quando não há itens) */
  pages: number;
}

export interface VendasPropostaQuery {
  /** Página, a partir de 1 */
  page?: number;
  /** Itens por página (até 100) */
  size?: number;
  /** Ordem: "campo" (crescente) ou "-campo" (decrescente) */
  sort?: "created_at" | "-created_at" | "valor" | "-valor" | null;
  /** Busca por palavras (início de palavra, sem acento) */
  q?: string | null;
  status?: "pedida" | "montada" | "enviada" | "aceita" | "recusada" | null;
}

export interface VendasPedidoProposta {
  /** Para quem é a proposta */
  cliente: string;
  /** Para onde a proposta vai */
  email?: string | null;
  /** O que o cliente pediu, nas palavras dele */
  pedido: string;
}

export interface VendasPropostaMudou {
  id: string;
  action: "pedida" | "montada" | "enviada" | "follow_up" | "aceita" | "recusada";
}

export interface VendasLead {
  nome: string;
  email?: string | null;
  telefone?: string | null;
  origem?: "site" | "instagram" | "whatsapp" | "indicacao" | "outro";
  interesse?: string | null;
  status?: "novo" | "qualificado" | "reuniao" | "nutricao" | "atendimento" | "cliente";
  reuniao_em?: string | null;
}

/** Leads: só os campos que mudam. */
export interface VendasLeadUpdate {
  /** Id do registro */
  id: string;
  nome?: string | null;
  email?: string | null;
  telefone?: string | null;
  origem?: "site" | "instagram" | "whatsapp" | "indicacao" | "outro" | null;
  interesse?: string | null;
  status?: "novo" | "qualificado" | "reuniao" | "nutricao" | "atendimento" | "cliente" | null;
  reuniao_em?: string | null;
}

/** Leads: página, busca, filtros e ordem pela URL. */
export interface VendasLeadQuery {
  /** Página, a partir de 1 */
  page?: number;
  /** Itens por página (até 100) */
  size?: number;
  /** Ordem: "campo" (crescente) ou "-campo" (decrescente) */
  sort?: "nome" | "-nome" | "created_at" | "-created_at" | null;
  /** Busca por palavras (início de palavra, sem acento) */
  q?: string | null;
  status?: "novo" | "qualificado" | "reuniao" | "nutricao" | "atendimento" | "cliente" | null;
  origem?: "site" | "instagram" | "whatsapp" | "indicacao" | "outro" | null;
}

export interface VendasLeadPage {
  items: VendasLeadItem[];
  /** Itens que atendem ao filtro, somando todas as páginas */
  total: number;
  page: number;
  size: number;
  /** Total de páginas (0 quando não há itens) */
  pages: number;
}

export interface VendasCliente {
  nome: string;
  email?: string | null;
  telefone?: string | null;
  ultima_compra?: string | null;
  campanha_em?: string | null;
}

/** Clientes: só os campos que mudam. */
export interface VendasClienteUpdate {
  /** Id do registro */
  id: string;
  nome?: string | null;
  email?: string | null;
  telefone?: string | null;
  ultima_compra?: string | null;
  campanha_em?: string | null;
}

/** Clientes: página, busca, filtros e ordem pela URL. */
export interface VendasClienteQuery {
  /** Página, a partir de 1 */
  page?: number;
  /** Itens por página (até 100) */
  size?: number;
  /** Ordem: "campo" (crescente) ou "-campo" (decrescente) */
  sort?: "nome" | "-nome" | "ultima_compra" | "-ultima_compra" | "created_at" | "-created_at" | null;
  /** Busca por palavras (início de palavra, sem acento) */
  q?: string | null;
}

/** Clientes: um registro. */
export interface VendasClienteItem {
  /** Id do registro */
  id: string;
  created_at: string | null;
  created_by: string | null;
  updated_at: string | null;
  updated_by: string | null;
  nome: string;
  email: string | null;
  telefone: string | null;
  ultima_compra: string | null;
  campanha_em: string | null;
}

export interface VendasClientePage {
  items: VendasClienteItem[];
  /** Itens que atendem ao filtro, somando todas as páginas */
  total: number;
  page: number;
  size: number;
  /** Total de páginas (0 quando não há itens) */
  pages: number;
}

/** svc-vendas · /api/v1/vendas */
export const vendas = {
  /** POST /api/v1/vendas/leads/receber · http · exige token */
  receberLead: (body: VendasReceberLead, options?: RequestOptions) =>
    request<VendasLeadItem>("POST", "/api/v1/vendas/leads/receber", body, options),
  /** GET /api/v1/vendas/propostas · http · exige token */
  propostas: (query?: VendasPropostaQuery, options?: RequestOptions) =>
    request<VendasPropostaPage>("GET", withQuery("/api/v1/vendas/propostas", query), undefined, options),
  /** POST /api/v1/vendas/propostas · http · exige token */
  pedirProposta: (body: VendasPedidoProposta, options?: RequestOptions) =>
    request<VendasProposta>("POST", "/api/v1/vendas/propostas", body, options),
  /** Cadastro Leads (core/resources.py) · /api/v1/vendas/leads · exige token */
  leads: {
    /** GET /api/v1/vendas/leads · página, busca, filtros e ordem */
    list: (query?: VendasLeadQuery, options?: RequestOptions) =>
      request<VendasLeadPage>("GET", withQuery("/api/v1/vendas/leads", query), undefined, options),
    /** GET /api/v1/vendas/leads/item?id= */
    get: (query: ResourceRef, options?: RequestOptions) =>
      request<VendasLeadItem>("GET", withQuery("/api/v1/vendas/leads/item", query), undefined, options),
    /** POST /api/v1/vendas/leads */
    create: (body: VendasLead, options?: RequestOptions) =>
      request<VendasLeadItem>("POST", "/api/v1/vendas/leads", body, options),
    /** POST /api/v1/vendas/leads/update · só os campos que vierem mudam */
    update: (body: VendasLeadUpdate, options?: RequestOptions) =>
      request<VendasLeadItem>("POST", "/api/v1/vendas/leads/update", body, options),
    /** POST /api/v1/vendas/leads/remove */
    remove: (body: ResourceRef, options?: RequestOptions) =>
      request<ResourceRemoved>("POST", "/api/v1/vendas/leads/remove", body, options),
    /** Campos, colunas e filtros: o que useResource e ResourceList usam para montar a tela. */
    meta: {"title": "Leads", "live": "vendas.leads", "fields": [{"name": "nome", "label": "Nome", "kind": "text", "required": true}, {"name": "email", "label": "E-mail", "kind": "email", "required": false}, {"name": "telefone", "label": "Telefone", "kind": "phone", "required": false}, {"name": "origem", "label": "Origem", "kind": "select", "required": false, "options": [{"value": "site", "label": "Site"}, {"value": "instagram", "label": "Instagram"}, {"value": "whatsapp", "label": "WhatsApp"}, {"value": "indicacao", "label": "Indicação"}, {"value": "outro", "label": "Outro"}]}, {"name": "interesse", "label": "O que ele quer", "kind": "textarea", "required": false}, {"name": "status", "label": "Situação", "kind": "select", "required": false, "options": [{"value": "novo", "label": "Novo"}, {"value": "qualificado", "label": "Qualificado"}, {"value": "reuniao", "label": "Reunião marcada"}, {"value": "nutricao", "label": "Nutrição"}, {"value": "atendimento", "label": "Atendimento humano"}, {"value": "cliente", "label": "Cliente"}]}, {"name": "reuniao_em", "label": "Reunião", "kind": "datetime", "required": false}], "columns": [{"key": "nome", "header": "Nome", "kind": "text", "sort": "nome"}, {"key": "email", "header": "E-mail", "kind": "email"}, {"key": "telefone", "header": "Telefone", "kind": "phone"}, {"key": "origem", "header": "Origem", "kind": "select"}, {"key": "status", "header": "Situação", "kind": "select"}], "filters": [{"name": "status", "label": "Situação", "options": [{"value": "novo", "label": "Novo"}, {"value": "qualificado", "label": "Qualificado"}, {"value": "reuniao", "label": "Reunião marcada"}, {"value": "nutricao", "label": "Nutrição"}, {"value": "atendimento", "label": "Atendimento humano"}, {"value": "cliente", "label": "Cliente"}]}, {"name": "origem", "label": "Origem", "options": [{"value": "site", "label": "Site"}, {"value": "instagram", "label": "Instagram"}, {"value": "whatsapp", "label": "WhatsApp"}, {"value": "indicacao", "label": "Indicação"}, {"value": "outro", "label": "Outro"}]}], "search": "nome, e-mail"} satisfies ResourceMeta,
  },
  /** Cadastro Clientes (core/resources.py) · /api/v1/vendas/clientes · exige token */
  clientes: {
    /** GET /api/v1/vendas/clientes · página, busca, filtros e ordem */
    list: (query?: VendasClienteQuery, options?: RequestOptions) =>
      request<VendasClientePage>("GET", withQuery("/api/v1/vendas/clientes", query), undefined, options),
    /** GET /api/v1/vendas/clientes/item?id= */
    get: (query: ResourceRef, options?: RequestOptions) =>
      request<VendasClienteItem>("GET", withQuery("/api/v1/vendas/clientes/item", query), undefined, options),
    /** POST /api/v1/vendas/clientes */
    create: (body: VendasCliente, options?: RequestOptions) =>
      request<VendasClienteItem>("POST", "/api/v1/vendas/clientes", body, options),
    /** POST /api/v1/vendas/clientes/update · só os campos que vierem mudam */
    update: (body: VendasClienteUpdate, options?: RequestOptions) =>
      request<VendasClienteItem>("POST", "/api/v1/vendas/clientes/update", body, options),
    /** POST /api/v1/vendas/clientes/remove */
    remove: (body: ResourceRef, options?: RequestOptions) =>
      request<ResourceRemoved>("POST", "/api/v1/vendas/clientes/remove", body, options),
    /** Campos, colunas e filtros: o que useResource e ResourceList usam para montar a tela. */
    meta: {"title": "Clientes", "live": "vendas.clientes", "fields": [{"name": "nome", "label": "Nome", "kind": "text", "required": true}, {"name": "email", "label": "E-mail", "kind": "email", "required": false}, {"name": "telefone", "label": "Telefone", "kind": "phone", "required": false}, {"name": "ultima_compra", "label": "Última compra", "kind": "date", "required": false}, {"name": "campanha_em", "label": "Última campanha", "kind": "date", "required": false}], "columns": [{"key": "nome", "header": "Nome", "kind": "text", "sort": "nome"}, {"key": "email", "header": "E-mail", "kind": "email"}, {"key": "telefone", "header": "Telefone", "kind": "phone"}, {"key": "ultima_compra", "header": "Última compra", "kind": "date", "sort": "ultima_compra"}, {"key": "campanha_em", "header": "Última campanha", "kind": "date"}], "filters": [], "search": "nome, e-mail"} satisfies ResourceMeta,
  },
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
  /** svc-administrativo · bus.live("administrativo.requisicoes", ...) */
  "administrativo.requisicoes": AdministrativoRequisicaoMudou;
  /** svc-administrativo · cadastro colaboradores (core/resources.py) */
  "administrativo.colaboradores": ResourceChanged;
  /** svc-administrativo · cadastro fornecedores (core/resources.py) */
  "administrativo.fornecedores": ResourceChanged;
  /** svc-administrativo · cadastro vencimentos (core/resources.py) */
  "administrativo.vencimentos": ResourceChanged;
  /** svc-agentes · bus.live("agentes.agentes", ...) */
  "agentes.agentes": AgentesAgenteMudou;
  /** svc-ai · bus.live("ai.uso", ...) */
  "ai.uso": AiRecorded;
  /** svc-atendimento · bus.live("atendimento.pedidos", ...) */
  "atendimento.pedidos": AtendimentoPedidoMudou;
  /** svc-conhecimento · bus.live("conhecimento.briefing", ...) */
  "conhecimento.briefing": ConhecimentoBriefingMudou;
  /** svc-conhecimento · bus.live("conhecimento.leituras", ...) */
  "conhecimento.leituras": ConhecimentoLeituraMudou;
  /** svc-conhecimento · cadastro itens (core/resources.py) */
  "conhecimento.itens": ResourceChanged;
  /** svc-financeiro · bus.live("financeiro.titulos", ...) */
  "financeiro.titulos": FinanceiroTituloMudou;
  /** svc-financeiro · bus.live("financeiro.faturas", ...) */
  "financeiro.faturas": FinanceiroFaturaMudou;
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
  /** svc-integracoes · bus.live("integracoes.cobrancas", ...) */
  "integracoes.cobrancas": IntegracoesCobrancaMudou;
  /** svc-integracoes · bus.live("integracoes.enviados", ...) */
  "integracoes.enviados": IntegracoesEnviadoMudou;
  /** svc-integracoes · bus.live("integracoes.servidores", ...) */
  "integracoes.servidores": IntegracoesServidorMudou;
  /** svc-juridico · cadastro contratos (core/resources.py) */
  "juridico.contratos": ResourceChanged;
  /** svc-juridico · cadastro certidoes (core/resources.py) */
  "juridico.certidoes": ResourceChanged;
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
  /** svc-vendas · bus.live("vendas.propostas", ...) */
  "vendas.propostas": VendasPropostaMudou;
  /** svc-vendas · cadastro leads (core/resources.py) */
  "vendas.leads": ResourceChanged;
  /** svc-vendas · cadastro clientes (core/resources.py) */
  "vendas.clientes": ResourceChanged;
  /** svc-webhooks · bus.live("webhooks.entrega", ...) */
  "webhooks.entrega": WebhooksDeliveryChanged;
}

/** Módulos (o MODULE de cada services/svc-<nome>/schemas.py): o meta.module das telas e os grupos do menu. */
export const appModules = {
  administrativo: { title: "Administrativo", description: "Pacote de ações administrativas do BPO: admissões, compras e vencimentos da empresa", category: "Pacotes", core: false },
  agentes: { title: "Agentes", description: "Agentes da empresa: instrução, ferramentas do catálogo, política e suíte de avaliação", category: "Sua empresa", core: false },
  ai: { title: "IA", description: "Modelos de IA, chaves e consumo", category: "Integrações", core: true },
  atendimento: { title: "Falar com a Cogniventure", description: "Pedidos de ajuda ao staff da Cogniventure, com resposta em até 4 horas", category: "Organização", core: true },
  conhecimento: { title: "Conhecimento", description: "Briefing da empresa e a base de conhecimento que os agentes consultam", category: "Sua empresa", core: false },
  financeiro: { title: "Financeiro", description: "Pacote de ações financeiras do BPO: contas a pagar, conciliação, cobrança e fechamento", category: "Pacotes", core: false },
  identity: { title: "Pessoas e acesso", description: "Contas, organizações, membros e convites", category: "Organização", core: true },
  integracoes: { title: "Integrações", description: "Conexões da empresa com o mundo de fora: caixa de entrada de documentos, banco e servidores MCP", category: "Integrações", core: false },
  juridico: { title: "Jurídico", description: "Pacote de ações jurídicas do BPO: contratos, publicações e certidões negativas", category: "Pacotes", core: false },
  notify: { title: "Avisos", description: "Avisos na tela e por e-mail", category: "Organização", core: true },
  plans: { title: "Plano", description: "Plano, módulos e consumo da organização", category: "Organização", core: true },
  processos: { title: "Processos", description: "Os processos que a Cogniventure executa para a empresa: sugeridos, descritos, desenhados e publicados", category: "Sua empresa", core: false },
  staff: { title: "Staff", description: "Área da equipe da Cogniventure: carteira de clientes, exceções, revisões e pedidos de ajuda", category: "Cogniventure", core: false },
  vendas: { title: "Vendas", description: "Pacote de ações de vendas do BPO: leads, propostas e reativação da carteira", category: "Pacotes", core: false },
  webhooks: { title: "Webhooks", description: "Eventos para os sistemas da organização", category: "Integrações", core: true },
} as const;

/** Nome de um módulo: o do serviço, sem svc-. */
export type ModuleName = keyof typeof appModules;
