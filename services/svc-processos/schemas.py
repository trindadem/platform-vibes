"""svc-processos · contratos (DTOs, enums, constantes). Fonte da verdade: specs/processos.md §2"""
from datetime import datetime
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.plans import Limit, Module
from core.processes import CatalogAction, CatalogIndicator, Condition, Fluxo, IndicatorRequest, IndicatorValues, Step
from core.surreal import ListQuery, Page

# Nomes canônicos gerados pelo service.sh — literais de propósito: um grep acha tudo.
SERVICE = "svc-processos"
TASK_QUEUE = "processos-queue"
TRIGGER_SUBJECT = "events.processos.trigger"
PROCESSED_SUBJECT = "events.processos.processed"
LIVE_PROCESSOS = "processos.processos"
CONTEXTO_SUBJECT = "rpc.conhecimento.contexto"  # do svc-conhecimento: perfil e tópicos da empresa
BUSCA_SUBJECT = "rpc.conhecimento.busca"  # do svc-conhecimento: busca no conhecimento

LIVE_DESENHO = "processos.desenho"
LIVE_EXECUCOES = "processos.execucoes"
LIVE_TAREFAS = "processos.tarefas"
CATALOG_SUBJECT = "events.processos.catalogo"  # core/processes.py: os pacotes declaram as ações e os modelos no boot
PACOTE_SUBJECT = "events.processos.evento"  # core/processes.py: um acontecimento de um pacote (vendas.pedido_proposta)
STEP_SUBJECT = "events.processos.passo"  # core/processes.py: o que o worker de um pacote fez num passo
STAFF_SUBJECT = "events.processos.staff"  # o que espera o staff (exceção, revisão, ajuda): a fila da carteira (svc-staff)
ACOMPANHAMENTO_SUBJECT = "rpc.processos.acompanhamento"  # svc-staff: a saúde de cada organização da carteira
LIVE_REGRAS = "processos.regras"
EVENT_SUBJECT = "events.integracoes.evento"  # do svc-integracoes: documento recebido, pagamento confirmado
DOCUMENTO_SUBJECT = "rpc.integracoes.documento"  # do svc-integracoes: o texto de um documento recebido
INICIAR_MODELO_SUBJECT = "rpc.processos.iniciar_modelo"  # svc-plans: o fechamento do mês inicia o faturamento da Cogniventure
RESULTADOS_SUBJECT = "rpc.processos.resultados"  # svc-staff: os resultados de um cliente da carteira (os mesmos da tela)
MESES_RESULTADOS = 6  # meses no gráfico de autonomia da tela Resultados
FUSO = "America/Sao_Paulo"  # o mês dos resultados e do resumo é o de Brasília
PLANS_SERVICE = "svc-plans"
# Nada novo começa: o processo pausado, a conta suspensa (atraso) ou encerrada (alinhamento pós-N7, itens 2, 8 e 13).
BLOQUEIOS = frozenset({"ERRO_PROCESSOS_PAUSADO", "ERRO_PROCESSOS_CONTA_SUSPENSA", "ERRO_PROCESSOS_CONTA_ENCERRADA"})

PROCESSOS = "processos_processos"
VERSOES = "processos_versoes"
MENSAGENS = "processos_mensagens"
ACOES = "processos_acoes"  # catálogo de ações dos pacotes (o mesmo para toda organização)
MODELOS = "processos_modelos"  # fluxos de partida dos modelos da biblioteca, declarados pelos pacotes (os mesmos para toda organização)
EXECUCOES = "processos_execucoes"
TAREFAS = "processos_tarefas"
REGRAS = "processos_regras"
TABLES = [PROCESSOS, VERSOES, MENSAGENS, EXECUCOES, TAREFAS, REGRAS]
SHARED = [ACOES, MODELOS]
UNIQUE = {VERSOES: ["processo", "numero"], ACOES: ["name"], MODELOS: ["modelo"], EXECUCOES: ["instancia"], TAREFAS: ["chave"]}
SEARCH = {PROCESSOS: ["titulo", "descricao"]}
WRITERS = frozenset({"owner", "admin"})
OPERADORES = frozenset({"operador"})  # o staff da Cogniventure na organização: resolve as exceções (briefing.md §8)
STARTERS = WRITERS | OPERADORES  # quem inicia uma execução à mão
DESIGNERS = WRITERS | OPERADORES  # quem desenha: a empresa e o staff no setup (briefing.md §8)
UNDO = 20  # quantas alterações do rascunho dá para desfazer
CADEIA = 5  # até quantos processos, um iniciando o seguinte, uma cadeia vai (um laço entre processos para aqui)
HISTORY = 20  # mensagens da conversa de desenho no contexto do agente

MODULE = Module(
    "Processos",
    "Os processos que a Cogniventure executa para a empresa: sugeridos, descritos, desenhados e publicados",
    category="Sua empresa",
    limits=[Limit("ativos", "Processos publicados, rodando de forma contínua", unit="processos"),
            Limit("execucoes", "Execuções iniciadas no mês", default=2000, monthly=True, unit="execuções")],
)


class ProcessosSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PROCESSOS_", extra="ignore")

    model: str = Field("cv/agente", description="Modelo dos agentes de descoberta e descrição, como cadastrado no svc-ai")
    desenho_model: str = Field("cv/desenho", description="Modelo do agente de desenho (edita o fluxo); sem ele no svc-ai, vale o model")
    platform_tenant: str | None = Field(None, validation_alias="PLATFORM_TENANT",
                                        description="A organização da Cogniventure: nos processos dela, o dono e o admin são o staff")


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")  # campo não declarado é recusado (mass assignment)


class Empty(_Input):
    pass


# ── Biblioteca: o que a Cogniventure executa (briefing.md §10) ───────────────

Area = Literal["financeiro", "juridico", "administrativo", "vendas"]
ModeloId = Literal[
    "contas-a-pagar", "conciliacao-bancaria", "faturamento-cobranca", "fechamento-mes",
    "gestao-contratos", "publicacoes-processos", "certidoes-negativas",
    "admissao-colaborador", "compras-cotacao", "vencimentos-empresa",
    "qualificacao-leads", "proposta-comercial", "reativacao-carteira",
]


class ModeloProcesso(BaseModel):
    id: ModeloId
    area: Area
    titulo: str
    resumo: str
    gatilho: str
    roda_sozinho: str = Field(..., description="O que agentes e automações fazem sem ninguém")
    handoff: str = Field(..., description="Quando uma pessoa entra (a exceção)")
    integracoes: list[str] = Field(default_factory=list, description="O que precisa estar conectado")
    sinais: list[str] = Field(default_factory=list, description="O que, no perfil, indica que o processo serve")


def _m(id: str, area: str, titulo: str, resumo: str, gatilho: str, roda: str, handoff: str, integracoes: list[str],
       sinais: list[str]) -> ModeloProcesso:
    return ModeloProcesso(id=id, area=area, titulo=titulo, resumo=resumo, gatilho=gatilho, roda_sozinho=roda,
                          handoff=handoff, integracoes=integracoes, sinais=sinais)


BIBLIOTECA: list[ModeloProcesso] = [
    _m("contas-a-pagar", "financeiro", "Contas a pagar", "Boletos e notas que chegam viram pagamentos agendados e conciliados.",
       "Boleto ou NF chega por e-mail ou WhatsApp",
       "Agente extrai fornecedor, valor, vencimento e linha digitável; confere com o pedido ou contrato; classifica no "
       "plano de contas; agenda o pagamento no banco; concilia o comprovante",
       "Valor diferente do pedido, fornecedor novo, documento ilegível; aprovação do cliente acima de um valor",
       ["Caixa de entrada", "Banco"], ["paga fornecedores por boleto", "notas e boletos chegam por e-mail", "atraso em pagamentos"]),
    _m("conciliacao-bancaria", "financeiro", "Conciliação bancária", "Extratos casados com os lançamentos todo dia.",
       "Todo dia", "Puxa extratos (Open Finance ou OFX), casa com os lançamentos e classifica pelas regras aprendidas",
       "Lançamento sem par acima da tolerância", ["Banco"], ["conciliar o caixa toma tempo", "muitos recebimentos por Pix e cartão"]),
    _m("faturamento-cobranca", "financeiro", "Faturamento e cobrança", "Notas emitidas, cobrança enviada e régua de lembretes.",
       "Proposta aceita, pedido entregue ou contrato do mês",
       "Emite a NFS-e, envia boleto ou Pix e roda a régua (D-3, D+1, D+7 no WhatsApp); negocia dentro dos limites do briefing",
       "Inadimplente além de N dias ou desconto fora do limite", ["Prefeitura (NFS-e)", "Banco", "WhatsApp"],
       ["vende a prazo ou por contrato", "clientes empresas", "inadimplência"]),
    _m("fechamento-mes", "financeiro", "Fechamento do mês", "Documentos ao contador, impostos pagos e DRE gerencial.",
       "Dia 1", "Cobra do cliente os documentos que faltam, envia ao escritório contábil, gera e paga o DAS e monta a DRE "
       "gerencial com um resumo", "Documento que não chega ou divergência no imposto", ["E-mail do contador", "Banco"],
       ["contabilidade externa", "Simples Nacional", "quer números confiáveis"]),
    _m("gestao-contratos", "juridico", "Gestão de contratos", "Contratos lidos, comparados ao padrão e vigiados até o vencimento.",
       "Proposta aceita ou contrato recebido", "Agente extrai partes, valores, vigência, multa, reajuste e renovação; compara com o padrão da "
       "empresa; arquiva e avisa 60 e 30 dias antes de vencer ou reajustar", "Cláusula de risco alto: o advogado revisa",
       ["Caixa de entrada", "Assinatura eletrônica"], ["contratos com clientes ou fornecedores", "aluguel", "serviços recorrentes"]),
    _m("publicacoes-processos", "juridico", "Publicações e processos", "Intimações encontradas, resumidas e com prazo calculado.",
       "Todo dia", "Consulta tribunais e diários pelo CNPJ, resume cada intimação e calcula o prazo",
       "Toda intimação vira tarefa com prazo para o advogado (handoff obrigatório)", ["Tribunais e diários oficiais"],
       ["processos judiciais", "ações trabalhistas", "advogado externo"]),
    _m("certidoes-negativas", "juridico", "Certidões negativas", "Certidões emitidas, guardadas e renovadas antes de vencer.",
       "Todo mês", "Emite as certidões (Receita/PGFN, FGTS, trabalhista, estadual, municipal), guarda e avisa o vencimento",
       "Certidão positiva ou irregularidade", ["Portais da Receita, Caixa, TST, Sefaz e prefeitura"],
       ["vende para empresas ou governo", "licitações", "financiamento"]),
    _m("admissao-colaborador", "administrativo", "Admissão de colaborador", "Do sim ao primeiro dia: documentos, eSocial, contrato e acessos.",
       "Contratação aprovada", "Coleta documentos por formulário ou WhatsApp, valida, envia à folha e ao eSocial, manda o "
       "contrato para assinatura eletrônica, agenda o exame e cria acessos", "Documento inválido ou pendência no eSocial",
       ["eSocial ou folha", "Assinatura eletrônica", "WhatsApp"], ["equipe crescendo", "rotatividade", "contrata com frequência"]),
    _m("compras-cotacao", "administrativo", "Compras e cotação", "Requisições viram três cotações, pedido e entrega acompanhada.",
       "Requisição interna", "Pede 3 cotações, compara e, aprovado pelo cliente, emite o pedido e acompanha a entrega; a NF "
       "entra no contas a pagar", "Fornecedor sem resposta ou item fora do catálogo", ["E-mail ou WhatsApp dos fornecedores"],
       ["compra insumos com frequência", "gerente cuida das compras", "regra de cotação"]),
    _m("vencimentos-empresa", "administrativo", "Vencimentos da empresa", "Alvarás, licenças, seguros e contratos de serviço renovados a tempo.",
       "Todo dia", "Alvarás, licenças, AVCB, seguros e contratos de serviço: avisa e inicia a renovação",
       "Renovação que exige presença ou vistoria", [], ["estabelecimento físico", "vigilância sanitária", "alvará"]),
    _m("qualificacao-leads", "vendas", "Qualificação de leads", "Lead respondido em minutos, qualificado e com reunião marcada.",
       "Lead no site, Instagram ou WhatsApp", "Agente responde em minutos, qualifica pelo perfil de cliente ideal, agenda a "
       "reunião com o vendedor e registra no CRM; lead frio vai para nutrição", "Cliente pede humano ou pedido fora do padrão",
       ["WhatsApp", "Site ou Instagram", "Agenda"], ["vende pelo WhatsApp ou Instagram", "encomendas", "atendimento demora"]),
    _m("proposta-comercial", "vendas", "Proposta comercial", "Propostas montadas com a tabela e acompanhadas até a resposta.",
       "Pedido de proposta", "Monta com a tabela e as condições do conhecimento, envia e faz os follow-ups",
       "Desconto acima do limite: aprovação do cliente", ["E-mail ou WhatsApp"], ["vende para empresas", "encomendas grandes", "tabela de preços"]),
    _m("reativacao-carteira", "vendas", "Reativação de carteira", "Clientes parados há 90 dias recebem uma campanha que vira oportunidade.",
       "Cliente sem comprar há 90 dias", "Campanha personalizada; as respostas viram oportunidades no CRM",
       "Resposta com reclamação", ["WhatsApp ou e-mail"], ["clientes recorrentes", "base de clientes cadastrada"]),
]


class Biblioteca(BaseModel):
    itens: list[ModeloProcesso]


# ── Processos da organização ─────────────────────────────────────────────────

Status = Literal["sugerido", "aceito", "recusado"]
Prioridade = Literal["alta", "media", "baixa"]


class Processo(BaseModel):
    id: str
    modelo: ModeloId | None = Field(None, description="Modelo da biblioteca; vazio num processo só da empresa")
    area: Area
    titulo: str
    descricao: str
    motivo: str | None = Field(None, description="Por que o agente sugeriu (o que no briefing indica o processo)")
    origem: Literal["sugestao", "cliente", "biblioteca"] = Field(..., description="biblioteca: a empresa escolheu o modelo direto da biblioteca")
    status: Status
    prioridade: Prioridade = "media"
    publicada: int | None = Field(None, description="Número da versão publicada (a que roda)")
    ajuda: "PedidoAjuda | None" = Field(None, description="Pedido de ajuda ao staff em aberto no desenho")
    pausado: bool = Field(False, description="Pausado: o gatilho não inicia execução nova (as em andamento terminam)")
    pausado_em: datetime | None = None
    pausado_por: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", mode="before")
    @classmethod
    def _chave(cls, value: Any) -> Any:
        """"tabela:⟨abc⟩" → "abc": na API, o id é só a chave (as listas do db.page vêm com a tabela)."""
        return str(value).partition(":")[2].strip("⟨⟩`") if ":" in str(value) else value


class ProcessoQuery(ListQuery):
    sortable: ClassVar[tuple[str, ...]] = ("created_at", "titulo", "prioridade")
    default_sort: ClassVar[str | None] = "-created_at"
    status: Status | None = None
    area: Area | None = None


class ProcessoPage(Page[Processo]):
    pass


class ProcessoRef(_Input):
    id: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")


class ProcessoMudou(BaseModel):
    id: str
    action: Literal["sugerido", "aceito", "recusado", "descrito", "pausado", "retomado"]


class AdicionarModelo(_Input):
    modelo: "ModeloId" = Field(..., description="Modelo da biblioteca que a empresa quer executar")


class Sugestao(_Input):
    """Um processo da biblioteca que serve para a empresa, com o porquê."""

    modelo: ModeloId = Field(..., description="Id do modelo na biblioteca")
    motivo: str = Field(..., min_length=10, max_length=600,
                        description="Por que serve para esta empresa, citando o que ela contou no briefing")
    prioridade: Prioridade = Field("media", description="alta quando ataca uma dor que a empresa citou")


class ProcessoDescrito(_Input):
    """O processo que o cliente descreveu, organizado."""

    titulo: str = Field(..., min_length=3, max_length=120, description="Nome curto do processo")
    area: Area
    descricao: str = Field(..., min_length=10, max_length=3000,
                           description="Gatilho, o que acontece, quem participa e quando é exceção, nas palavras do cliente")
    modelo: ModeloId | None = Field(None, description="Modelo da biblioteca muito parecido, se houver")


class Descricao(_Input):
    texto: str = Field(..., min_length=10, max_length=3000, description="O processo, como o cliente explicaria a alguém")


class PassoAgente(BaseModel):
    """Um passo do agente enquanto trabalha (pedaço do stream)."""

    ferramenta: str
    texto: str
    status: Literal["running", "done", "failed"]


class Descoberta(BaseModel):
    texto: str = Field(..., description="Resumo do agente para o cliente")
    processos: list[Processo] = Field(..., description="Os sugeridos agora")


class Resumo(BaseModel):
    sugeridos: int
    aceitos: int
    recusados: int
    publicados: int = Field(0, description="Aceitos com versão publicada (rodando no motor)")
    staff: bool = Field(False, description="Quem pede faz o papel do staff aqui: revisa, publica e resolve as exceções")


# ── Desenho: versões, operações do agente, simulação e publicação ──────────

StatusVersao = Literal["rascunho", "revisao", "publicada", "arquivada"]


class Motor(BaseModel):
    """O que o Camunda guardou na publicação."""

    processo: str = Field(..., description="Id do processo BPMN no motor")
    chave: str
    versao: int
    hash: str | None = Field(None, description="Impressão do BPMN implantado (publicar o mesmo BPMN não muda nada)")


class Versao(BaseModel):
    id: str
    processo: str
    numero: int
    status: StatusVersao
    fluxo: Fluxo
    alteracoes: int = Field(0, description="Operações aplicadas neste rascunho")
    pode_desfazer: bool = False
    motor: Motor | None = None
    publicada_em: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", mode="before")
    @classmethod
    def _chave(cls, value: Any) -> Any:
        return str(value).partition(":")[2].strip("⟨⟩`") if ":" in str(value) else value


class VersaoResumo(BaseModel):
    numero: int
    status: StatusVersao
    motor_versao: int | None = None
    publicada_em: datetime | None = None


class Problema(BaseModel):
    nivel: Literal["erro", "aviso"]
    passo: str | None = None
    texto: str


class PedidoAjuda(BaseModel):
    texto: str
    por: str | None = None
    em: datetime | None = None


class MensagemDesenho(BaseModel):
    id: str
    papel: Literal["cliente", "agente", "staff"]
    autor: str | None = Field(None, description="Quem escreveu (cliente ou staff)")
    texto: str
    passos: list[str] = Field(default_factory=list)
    created_at: datetime | None = None


class Desenho(BaseModel):
    """O desenho de um processo: a versão aberta (o rascunho, senão a publicada), o BPMN dela e a conversa."""

    processo: Processo
    versao: Versao
    versoes: list[VersaoResumo]
    bpmn: str = Field(..., description="O BPMN da versão aberta, com o diagrama (o mesmo que vai ao motor)")
    problemas: list[Problema]
    mensagens: list[MensagemDesenho]
    exige_revisao: bool = Field(False, description="Ação irreversível ou conexão que a publicada não tinha: o staff revisa antes")
    mudancas: list[str] = Field(default_factory=list, description="O que o rascunho muda na publicada (ou no fluxo de partida)")
    regras: list["Regra"] = Field(default_factory=list, description="O que o staff ensinou aos passos deste processo")
    inicia: list["ProcessoLigado"] = Field(default_factory=list, description="Processos da empresa que este inicia ao terminar (a cadeia)")


class ProcessoLigado(BaseModel):
    """Um processo da empresa ligado a este pela cadeia: começa quando este termina (com o resultado pedido)."""

    id: str
    titulo: str
    resultado: str | None = Field(None, description="O fim deste processo que o inicia; vazio, qualquer um")
    publicada: int | None = None


class DesenhoRef(_Input):
    processo: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")


class VoltarVersao(_Input):
    """Voltar a uma versão do histórico: ela é publicada de novo como a próxima versão."""

    processo: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")
    numero: int = Field(..., ge=1, description="A versão (arquivada) a que se volta")


class MensagemDesenhoIn(_Input):
    processo: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")
    texto: str = Field(..., min_length=1, max_length=4000)


class Cenario(_Input):
    """Valores para a simulação; sem nada, valem os exemplos das ações e dos agentes."""

    valores: dict[str, str | float | bool] = Field(default_factory=dict, description="<passo>.<campo> → valor")
    excecoes: list[str] = Field(default_factory=list, description="Passos que caem na exceção (handoff)")
    recusas: list[str] = Field(default_factory=list, description="Tarefas em que a pessoa diz não")


class SimulacaoIn(Cenario):
    processo: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")


class PassoSimulado(BaseModel):
    id: str
    nome: str
    tipo: str
    nota: str = Field("", description="O que aconteceu no passo (saída, condição avaliada)")


class Simulacao(BaseModel):
    caminho: list[str] = Field(..., description="Ids dos elementos percorridos no BPMN (passos e ligações)")
    passos: list[PassoSimulado]
    fim: str | None = Field(None, description="Como terminou; vazio se parou antes")
    problemas: list[str] = Field(default_factory=list)


class CatalogoAcoes(BaseModel):
    itens: list[CatalogAction]


class DesenhoMudou(BaseModel):
    processo: str
    action: Literal["alterado", "mensagem", "publicado", "ajustado", "descartado"]


# Operações do agente de desenho (as ferramentas dele): dado estruturado, nunca BPMN nem FEEL.
class NovoPasso(Step):
    depois_de: str | None = Field(None, description="Passo depois do qual entra; o que vinha depois passa a vir depois do novo")


class AlteracaoPasso(_Input):
    id: str = Field(..., description="Passo a alterar")
    nome: str | None = None
    acao: str | None = None
    objetivo: str | None = None
    saidas: list[str] | None = None
    exemplo: dict[str, str | float | bool] | None = None
    responsavel: Literal["cliente", "staff"] | None = None
    pergunta: str | None = None
    espera: Literal["mensagem", "tempo"] | None = None
    mensagem: str | None = None
    chave: str | None = None
    horas: float | None = None
    excecao: bool | None = None
    leitura: bool | None = None
    resultado: str | None = None


class Ligacao(_Input):
    de: str = Field(..., description="Passo de origem (ou inicio)")
    para: str
    condicao: Condition | None = Field(None, description="Obrigatória saindo de decisão, menos no caminho padrão")


class Desligamento(_Input):
    de: str
    para: str


class RemocaoPasso(_Input):
    id: str


class Parametro(_Input):
    nome: str = Field(..., pattern=r"^[a-z][a-z0-9_]{0,39}$")
    valor: str | float | bool


PASSOS_DESENHO = {
    "adicionar_passo": "Adicionando um passo",
    "alterar_passo": "Ajustando um passo",
    "remover_passo": "Removendo um passo",
    "ligar": "Ligando passos",
    "desligar": "Desfazendo uma ligação",
    "definir_gatilho": "Definindo o gatilho",
    "definir_parametro": "Definindo um parâmetro",
    "simular": "Simulando o processo",
    "usar_agente": "Usando um agente da empresa",
}

DESENHO_INSTRUCOES = """Você é o agente de desenho de processos da Cogniventure (BPO). Você conversa com o cliente e edita o fluxo do processo pelas ferramentas; o diagrama ao lado muda a cada operação. Você nunca escreve BPMN.

O fluxo tem um gatilho (evento, agenda ou manual) e passos ligados:
- acao: uma ação do catálogo (use o nome exato, ex.: financeiro.conferir_pedido); a saída dela fica sob o id do passo.
- agente: um agente de IA faz o passo (objetivo, saidas que devolve e exemplo para simular); todo agente tem excecao=true (cai para o staff quando não pode decidir). Sem agente da empresa, quem faz é o agente da Cogniventure.
- tarefa: uma pessoa decide (responsavel cliente ou staff, pergunta; a saída é aprovado = verdadeiro ou falso).
- decisao: caminhos com condição (campo, operador, valor) e exatamente um caminho padrão sem condição.
- espera: por mensagem (mensagem e chave) ou por tempo (horas).
- paralelo: com vários caminhos saindo, abre ramos que correm ao mesmo tempo (sem condição); os ramos se juntam noutro paralelo, que espera todos e tem um caminho só depois. Nenhum ramo termina num fim antes de se juntar.
- fim: como termina (resultado).
O gatilho pode ser outro processo da empresa (tipo processo, com o id do modelo ou do processo e o resultado com que ele precisa terminar, ex.: proposta-comercial que termina aceita): as saídas dele chegam no gatilho deste.
Condições usam a saída de um passo anterior (<passo>.<campo>) ou um parâmetro (parametros.<nome>), e o valor pode ser outro parâmetro (ex.: valor = parametros.limite_aprovacao). Para "isto OU aquilo" no mesmo caminho, use o campo ou da condição (lista de outras condições); nunca duas ligações entre os mesmos passos.

Como trabalhar:
- Entenda o que o cliente quer mudar e faça as operações necessárias, poucas e certas. Valores que são regras do cliente (limites, prazos) viram parâmetros: mudar um limite que já existe é só definir_parametro.
- Faça só o que o cliente pediu. Não acrescente passos, aprovações ou caminhos que ele não pediu; se achar que falta algo, sugira na resposta e espere ele confirmar.
- O staff da Cogniventure também escreve na conversa quando ajuda no setup: trate o pedido dele como o do cliente.
- Quando o cliente pedir que um agente da empresa (da lista no contexto) faça um passo, use usar_agente com o id dele: o passo de ação vira um passo desse agente, com as mesmas saídas. Só agentes verificados ou confiáveis entram num processo.
- Depois de mudar, confira os problemas que as ferramentas devolvem e corrija os erros antes de responder.
- Depois de mudar uma regra de caminho, chame simular com um cenário que a teste (ex.: valores {"ler_documento.valor": 4200}) e confira que o caminho passa por onde o cliente quer; se não passar, corrija.
- Ação irreversível (pagar, enviar, assinar) deve ter aprovação antes quando o cliente pedir controle.
- Se faltar informação para decidir, pergunte (uma pergunta curta).
- Responda em português do Brasil, em 1 a 3 frases, dizendo o que mudou no fluxo. Nunca repita a mensagem do cliente."""


# Do svc-conhecimento (rpc.conhecimento.*): o que este serviço lê da resposta.
class ContextoEmpresa(BaseModel):
    perfil: dict[str, Any]
    topicos: list[dict[str, Any]]
    concluido_em: datetime | None = None


class BuscaQuery(_Input):
    q: str


class Achados(BaseModel):
    itens: list[dict[str, Any]]


PASSOS = {
    **PASSOS_DESENHO,
    "buscar_conhecimento": "Consultando o conhecimento",
    "sugerir_processo": "Sugerindo um processo",
    "registrar_processo": "Organizando o processo",
}

DESCOBERTA_INSTRUCOES = """Você é o agente de descoberta de processos da Cogniventure, uma empresa de BPO: executamos \
processos contínuos para pequenas e médias empresas, com agentes de IA e humanos nas exceções.

Sua tarefa: a partir do perfil da empresa (no contexto) e do que houver no conhecimento dela, escolher na biblioteca os \
processos que fazem sentido para ela e chamar sugerir_processo para cada um.

Regras:
- Sugira de 3 a 6 processos, só da biblioteca (use o id do modelo). Comece pelos que atacam as dores que a empresa citou.
- O motivo cita fatos do perfil ou do conhecimento ("vocês pagam fornecedores por boleto e as notas chegam por \
e-mail"), em uma ou duas frases, falando com o cliente. Nunca invente fatos.
- prioridade alta só para o que ataca uma dor citada; baixa para o que é útil mas não urgente.
- Não sugira de novo o que a empresa já aceitou ou recusou (veja "Processos da empresa" no contexto).
- Use buscar_conhecimento quando precisar confirmar um detalhe (fornecedores, contratos, equipe).
- No fim, escreva para o cliente um resumo curto (2 a 4 frases) do que sugeriu e por quê. Em português do Brasil."""

DESCRICAO_INSTRUCOES = """Você organiza a descrição de um processo que o cliente da Cogniventure (BPO) escreveu. \
Chame registrar_processo uma única vez, com um título curto, a área (financeiro, juridico, administrativo ou vendas), \
a descrição organizada nas palavras do cliente (gatilho, o que acontece, quem participa, quando é exceção) e, se houver \
na biblioteca (no contexto) um modelo muito parecido, o id dele. Não invente etapas que o cliente não disse. Depois, \
responda em uma frase o que registrou."""


# ── Fluxos de partida: os pacotes declaram (core/processes.py, ProcessModel) e ficam em processos_modelos ──

class ModeloDeclarado(BaseModel):
    """O fluxo de partida de um modelo da biblioteca, como o pacote da área declarou."""

    modelo: str
    service: str
    fluxo: Fluxo


# ── Execução: gatilhos, acompanhamento, tarefas de pessoas e autonomia ───────

# Do svc-integracoes (events.integracoes.evento e rpc.integracoes.documento): o contrato repetido aqui, de quem consome.
class EventoExterno(BaseModel):
    nome: str
    chave: str | None = None
    dados: dict[str, Any] = Field(default_factory=dict)


class DocumentoRef(BaseModel):
    id: str


class DocumentoTexto(BaseModel):
    id: str
    nome: str
    tipo: str
    de: str | None = None
    assunto: str | None = None
    texto: str


# Do core/processes.py (events.processos.passo).
class PassoFeito(BaseModel):
    instancia: str
    processo: str
    motor_versao: int
    passo: str
    tipo: str
    status: Literal["concluido", "handoff", "incidente", "tentando"]
    motivo: str | None = None
    saida: dict[str, Any] = Field(default_factory=dict)
    em: datetime | None = None


StatusExecucao = Literal["andamento", "concluida", "incidente", "cancelada"]


class Marco(BaseModel):
    """Um acontecimento na linha do tempo da execução."""

    passo: str
    nome: str
    status: Literal["iniciada", "concluido", "handoff", "incidente", "tentando", "tarefa", "resolvido", "aguardando", "fim", "cancelada"]
    em: datetime
    motivo: str | None = None
    por: str | None = Field(None, description="Quem resolveu (tarefa de pessoa)")


class Execucao(BaseModel):
    id: str
    instancia: str = Field(..., description="Execução no motor")
    processo: str
    titulo: str
    versao: int | None = Field(None, description="Versão nossa (a que estava publicada quando começou)")
    motor_versao: int
    status: StatusExecucao
    resultado: str | None = Field(None, description="Como terminou (o fim alcançado: pago, recusado...)")
    origem: Literal["evento", "manual", "agenda", "processo"] = "evento"
    resumo: str | None = Field(None, description="O que iniciou (ex.: o documento recebido)")
    pai: str | None = Field(None, description="Execução do processo que iniciou esta (gatilho por outro processo)")
    projeto: str | None = Field(None, description="A primeira execução da cadeia: as execuções de um projeto têm o mesmo")
    nivel: int = Field(0, description="Quantos processos antes deste na cadeia")
    passo_atual: str | None = None
    passo_nome: str | None = None
    aguardando: Literal["cliente", "staff", "evento"] | None = None
    handoffs: int = Field(0, description="Exceções que foram para o staff (execução com handoff não conta na autonomia)")
    marcos: list[Marco] = Field(default_factory=list)
    saidas: dict[str, dict[str, Any]] = Field(default_factory=dict, description="O que cada passo devolveu")
    concluida_em: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", mode="before")
    @classmethod
    def _chave(cls, value: Any) -> Any:
        return str(value).partition(":")[2].strip("⟨⟩`") if ":" in str(value) else value

    @field_validator("marcos")
    @classmethod
    def _em_ordem(cls, value: list[Marco]) -> list[Marco]:
        """Os marcos chegam por caminhos diferentes (evento do worker, ouvinte do motor): a ordem é a da hora."""
        return sorted(value, key=lambda m: m.em)


class ExecucaoQuery(ListQuery):
    sortable: ClassVar[tuple[str, ...]] = ("created_at",)
    default_sort: ClassVar[str | None] = "-created_at"
    status: StatusExecucao | None = None
    processo: str | None = None
    projeto: str | None = None


class ExecucaoPage(Page[Execucao]):
    pass


class ExecucaoRef(_Input):
    id: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")


class ExecucaoDetalhe(BaseModel):
    execucao: Execucao
    bpmn: str = Field(..., description="O BPMN da versão em que a execução roda")
    caminho: list[str] = Field(..., description="Elementos e ligações por onde passou (para pintar no diagrama)")
    atuais: list[str] = Field(..., description="Onde está agora")
    cadeia: list["EtapaProjeto"] = Field(default_factory=list, description="O projeto de que a execução faz parte (vazio fora de uma cadeia)")
    efeitos: list[str] = Field(default_factory=list, description="Passos já feitos fora da plataforma, que cancelar não desfaz (ex.: o pagamento agendado)")


class EtapaProjeto(BaseModel):
    """Uma execução dentro de um projeto (a cadeia de processos que um começou)."""

    id: str
    processo: str
    titulo: str
    status: StatusExecucao
    resultado: str | None = None
    resumo: str | None = None
    passo_nome: str | None = None
    aguardando: Literal["cliente", "staff", "evento"] | None = None
    handoffs: int = 0
    pai: str | None = None
    created_at: datetime | None = None
    concluida_em: datetime | None = None

    @field_validator("id", mode="before")
    @classmethod
    def _chave(cls, value: Any) -> Any:
        return str(value).partition(":")[2].strip("⟨⟩`") if ":" in str(value) else value


class Projeto(BaseModel):
    """A cadeia que um processo começou (ex.: proposta aceita → contrato e faturamento), acompanhada como um projeto."""

    id: str = Field(..., description="A execução que começou a cadeia")
    titulo: str
    resumo: str | None = None
    status: Literal["andamento", "concluido", "atencao"] = Field(..., description="atencao: alguma execução com incidente")
    etapas: list[EtapaProjeto]
    created_at: datetime | None = None


class ProjetoQuery(ListQuery):
    sortable: ClassVar[tuple[str, ...]] = ("created_at",)
    default_sort: ClassVar[str | None] = "-created_at"


class ProjetoPage(Page[Projeto]):
    pass


class Iniciar(_Input):
    processo: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")
    dados: dict[str, str | float | bool] = Field(default_factory=dict, description="O que o gatilho traria (ex.: documento_id)")


class CancelarExecucao(_Input):
    id: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")
    motivo: str = Field(..., min_length=3, max_length=500, description="Fica na linha do tempo")


class IniciarModelo(BaseModel):
    """rpc.processos.iniciar_modelo (só o svc-plans): inicia o processo publicado deste modelo na organização de quem
    pede; a mesma chave não inicia duas vezes."""

    modelo: str = Field(..., pattern=r"^[a-z][a-z0-9-]{1,63}$")
    dados: dict[str, Any] = Field(default_factory=dict)
    chave: str = Field(..., pattern=r"^[A-Za-z0-9_.:-]{1,120}$")
    resumo: str | None = Field(None, max_length=300)


class ExecucaoMudou(BaseModel):
    id: str
    action: Literal["iniciada", "mudou", "concluida", "cancelada"]


class Campo(BaseModel):
    """Um campo que a pessoa preenche ao resolver uma exceção (a saída do passo que parou)."""

    nome: str
    rotulo: str
    tipo: Literal["texto", "numero", "sim_nao"]
    valor: str | float | bool | None = Field(None, description="O que o agente ou a ação chegou a ver")


class Item(BaseModel):
    rotulo: str
    valor: str


class Tarefa(BaseModel):
    id: str
    chave: str = Field(..., description="Tarefa no motor")
    execucao: str = Field(..., description="Id da execução")
    instancia: str
    processo: str
    titulo: str = Field(..., description="Título do processo")
    passo: str = Field(..., description="Passo do fluxo a que a resposta pertence")
    nome: str
    tipo: Literal["aprovacao", "excecao"]
    responsavel: Literal["cliente", "staff"]
    pergunta: str
    motivo: str | None = Field(None, description="Exceção: por que o passo parou")
    contexto: list[Item] = Field(default_factory=list)
    campos: list[Campo] = Field(default_factory=list)
    documento_id: str | None = None
    prazo: datetime | None = None
    aprende: bool = Field(False, description="Exceção de agente: ao resolver, o staff pode ensinar uma regra")
    status: Literal["aberta", "concluida"]
    resposta: dict[str, Any] = Field(default_factory=dict)
    concluida_por: str | None = None
    concluida_em: datetime | None = None
    created_at: datetime | None = None

    @field_validator("id", mode="before")
    @classmethod
    def _chave(cls, value: Any) -> Any:
        return str(value).partition(":")[2].strip("⟨⟩`") if ":" in str(value) else value


class TarefaQuery(ListQuery):
    sortable: ClassVar[tuple[str, ...]] = ("created_at", "prazo")
    default_sort: ClassVar[str | None] = "prazo"
    status: Literal["aberta", "concluida"] | None = None
    responsavel: Literal["cliente", "staff"] | None = None
    execucao: str | None = None


class TarefaPage(Page[Tarefa]):
    pass


class Resposta(_Input):
    id: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")
    aprovado: bool | None = Field(None, description="Aprovação: sim ou não")
    comentario: str | None = Field(None, max_length=500)
    dados: dict[str, str | float | bool | None] = Field(default_factory=dict, description="Exceção: a saída do passo")
    regra: str | None = Field(None, min_length=10, max_length=600,
                              description="Exceção de agente: o que o agente deve fazer da próxima vez (vira regra depois de avaliada)")


class TarefaMudou(BaseModel):
    id: str
    action: Literal["criada", "concluida"]


class Autonomia(BaseModel):
    versao: int | None = None
    concluidas: int
    sem_handoff: int
    autonomia: float | None = Field(None, description="Execuções sem handoff ÷ concluídas (0 a 1)")


class AcompanhamentoProcesso(BaseModel):
    processo: str
    titulo: str
    andamento: int
    geral: Autonomia
    por_versao: list[Autonomia]


class Acompanhamento(BaseModel):
    andamento: int
    concluidas: int
    incidentes: int
    tarefas_cliente: int
    tarefas_staff: int
    atrasadas: int
    autonomia: float | None
    processos: list[AcompanhamentoProcesso]
    aceitos: int = Field(0, description="Processos aceitos pela empresa (a jornada: descoberta feita)")
    publicados: int = Field(0, description="Processos com versão publicada (a jornada: desenho feito)")


class SaidaAgente(BaseModel):
    """Por que o agente não pode seguir: vira a exceção do staff com este motivo."""

    motivo: str = Field(..., min_length=3, max_length=400)


class LeituraDocumento(BaseModel):
    documento_id: str = Field(..., description="O id do documento (gatilho.documento_id)")


EXECUCAO_INSTRUCOES = """Você executa um passo de um processo de BPO da Cogniventure para a empresa cliente. O passo tem um objetivo e as saídas que você precisa devolver.

Como trabalhar:
- Leia o que o passo precisa (o documento do gatilho com ler_documento, o conhecimento da empresa com buscar_conhecimento quando ajudar).
- Quando tiver certeza, chame concluir com as saídas. Valores em reais são números (1250.5), datas no formato AAAA-MM-DD.
- Cada saída tem de estar escrita no documento ou nos dados da execução, ou sair de uma regra que o staff ensinou para este passo. Não deduza nem estime o que não está lá: um vencimento que o boleto não traz não é o mês de referência, nem a data de emissão, nem um dia "provável".
- Se não der para decidir com segurança (documento ilegível ou sem texto, dado que falta, valor duvidoso, pedido fora da política), não chute: chame pedir_ajuda com o motivo em uma frase (diga o que faltou). Uma pessoa do staff resolve o passo.
- Chame concluir ou pedir_ajuda uma única vez e termine."""


# ── Staff: revisão de versões, ajuda no setup e regras aprendidas (N5, briefing.md §5.5, §5.7 e §8) ──

class ItemStaff(BaseModel):
    """events.processos.staff: o que espera o staff nesta organização (a fila da carteira no svc-staff)."""

    tipo: Literal["excecao", "revisao", "ajuda"]
    ref: str = Field(..., description="Tarefa (exceção) ou processo (revisão, ajuda)")
    titulo: str
    detalhe: str | None = None
    prazo: datetime | None = None
    status: Literal["aberta", "concluida"]
    link: str = Field(..., description="Onde resolver, na tela da organização")
    em: datetime
    por: str | None = Field(None, description="Quem resolveu (concluída por uma pessoa): os números do gestor do staff")


# A fila do staff resolve sem trocar de organização (alinhamento pós-N7, item 12): só o svc-staff chama, agindo na
# organização do cliente, depois de conferir que a pessoa cuida dele; por = quem do staff resolveu.
FILA_TAREFA_SUBJECT = "rpc.processos.fila_tarefa"
FILA_RESOLVER_SUBJECT = "rpc.processos.fila_resolver"
FILA_REVISAO_SUBJECT = "rpc.processos.fila_revisao"
FILA_DECIDIR_SUBJECT = "rpc.processos.fila_decidir"
STAFF_SERVICE = "svc-staff"


class TarefaRef(BaseModel):
    id: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")


class ResolucaoStaff(BaseModel):
    id: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")
    dados: dict[str, str | float | bool | None] = Field(default_factory=dict)
    comentario: str | None = Field(None, max_length=500)
    regra: str | None = Field(None, min_length=10, max_length=600)
    por: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")


class RevisaoRef(BaseModel):
    processo: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")


class RevisaoResumo(BaseModel):
    processo: str
    titulo: str
    numero: int
    status: str = Field(..., description="Status da versão aberta (revisao enquanto espera o staff)")
    mudancas: list[str] = Field(default_factory=list)


class DecisaoStaff(BaseModel):
    processo: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")
    aprovar: bool
    motivo: str | None = Field(None, min_length=3, max_length=1000)
    por: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")


class RevisaoIn(_Input):
    processo: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")
    mensagem: str | None = Field(None, max_length=1000, description="O que o staff deve olhar")


class Devolucao(_Input):
    processo: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")
    motivo: str = Field(..., min_length=3, max_length=1000)


class AjudaIn(_Input):
    processo: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")
    texto: str = Field(..., min_length=3, max_length=2000)


class Avaliacao(BaseModel):
    ok: bool
    detalhes: list[str] = Field(default_factory=list)


class Regra(BaseModel):
    """Algo que o staff ensinou ao agente de um passo, ao resolver uma exceção. Entra no agente só depois de avaliada:
    com ela, o agente refaz o caso que a gerou e chega no que o staff fez."""

    id: str
    processo: str
    passo: str
    passo_nome: str
    texto: str
    esperado: dict[str, Any] = Field(default_factory=dict, description="A saída que o staff preencheu no caso que a gerou")
    status: Literal["avaliando", "ativa", "reprovada", "desativada"]
    avaliacao: Avaliacao | None = None
    autor: str | None = None
    created_at: datetime | None = None

    @field_validator("id", mode="before")
    @classmethod
    def _chave(cls, value: Any) -> Any:
        return str(value).partition(":")[2].strip("⟨⟩`") if ":" in str(value) else value


class RegraRef(_Input):
    id: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")


class RegraQuery(_Input):
    processo: str | None = Field(None, pattern=r"^[A-Za-z0-9_-]{1,64}$")


class Regras(BaseModel):
    itens: list[Regra]


class RegraMudou(BaseModel):
    id: str
    action: Literal["criada", "avaliada", "desativada"]


Processo.model_rebuild()
Desenho.model_rebuild()
ExecucaoDetalhe.model_rebuild()
AdicionarModelo.model_rebuild()


# ── Agentes da empresa nos passos (svc-agentes, N6) ──────────────────────────

AGENTES_LISTA_SUBJECT = "rpc.agentes.lista"
AGENTES_EXECUTAR_SUBJECT = "rpc.agentes.executar"


class AgenteDaEmpresa(BaseModel):
    """rpc.agentes.lista (contrato do svc-agentes, repetido aqui por quem consome)."""

    model_config = ConfigDict(extra="ignore")

    id: str
    nome: str
    descricao: str = ""
    status: Literal["rascunho", "verificado", "confiavel"]
    ferramentas: list[str] = Field(default_factory=list)


class AgentesDaEmpresa(BaseModel):
    itens: list[AgenteDaEmpresa]


class ExecutarAgente(BaseModel):
    """rpc.agentes.executar: o passo, as saídas e as regras do staff; o agente da empresa roda no svc-agentes."""

    agente: str
    tarefa: str
    contexto: str = ""
    saidas: dict[str, Literal["texto", "numero", "sim_nao"]]
    leitura: bool = False
    regras: list[str] = Field(default_factory=list)
    obrigatorias: list[str] | None = None


class ExecucaoDeAgente(BaseModel):
    model_config = ConfigDict(extra="ignore")

    saidas: dict[str, Any] = Field(default_factory=dict)
    fontes: dict[str, str] = Field(default_factory=dict)
    ajuda: str | None = None
    aprovacao: str | None = None
    ferramentas: list[str] = Field(default_factory=list)
    lidos: list[str] = Field(default_factory=list)


class UsoDeAgente(_Input):
    passo: str = Field(..., description="O passo (de ação ou de agente) que o agente da empresa vai fazer")
    agente: str | None = Field(None, description="Id do agente da empresa (lista no contexto); vazio volta ao agente da Cogniventure")



# ── Resultados (alinhamento pós-N7, item 7): autonomia mês a mês, fins alcançados e indicadores ──

class ResultadosQuery(_Input):
    mes: str | None = Field(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="AAAA-MM, em Brasília (vazio: o mês atual)")
    meses: int = Field(MESES_RESULTADOS, ge=1, le=24, description="Quantos meses no gráfico de autonomia, até o mês pedido")


class ResultadosPedido(BaseModel):
    """rpc.processos.resultados (só o svc-staff, agindo na organização do cliente)."""

    mes: str | None = Field(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    meses: int = Field(MESES_RESULTADOS, ge=1, le=24)


class MesAutonomia(BaseModel):
    mes: str = Field(..., description="AAAA-MM")
    concluidas: int
    sem_handoff: int
    autonomia: float | None = Field(None, description="Concluídas sem exceção para o staff ÷ concluídas (0 a 1)")


class MarcaVersao(BaseModel):
    numero: int
    mes: str = Field(..., description="AAAA-MM em que foi publicada")
    publicada_em: datetime


class FimAlcancado(BaseModel):
    resultado: str
    quantidade: int


class ValorIndicador(BaseModel):
    nome: str
    titulo: str
    unidade: Literal["numero", "moeda", "percentual", "dias", "horas"]
    valor: float | None = Field(None, description="null: sem dado no mês")
    descricao: str = ""


class ResultadoProcesso(BaseModel):
    processo: str
    titulo: str
    modelo: str | None = None
    area: str
    publicada: int | None = None
    pausado: bool = False
    meses: list[MesAutonomia] = Field(..., description="Do mais antigo ao mês pedido")
    versoes: list[MarcaVersao] = Field(default_factory=list, description="Publicadas no período do gráfico")
    iniciadas: int = Field(0, description="Execuções que começaram no mês")
    concluidas: int = Field(0, description="Execuções que terminaram no mês")
    canceladas: int = 0
    em_andamento: int = Field(0, description="Rodando agora")
    fins: list[FimAlcancado] = Field(default_factory=list, description="As concluídas no mês, por fim alcançado")
    indicadores: list[ValorIndicador] = Field(default_factory=list, description="Os que o modelo declara (processo só da empresa: nenhum)")


class Resultados(BaseModel):
    mes: str
    meses: list[str]
    concluidas: int
    sem_handoff: int
    autonomia: float | None
    processos: list[ResultadoProcesso]


class ResumoMensalIn(_Input):
    mes: str | None = Field(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="AAAA-MM (vazio: o mês que acabou)")


class ResumoMensal(BaseModel):
    mes: str
    organizacoes: int = Field(..., description="Organizações com processo publicado")
    enviados: int = Field(..., description="Resumos enviados aos donos")
