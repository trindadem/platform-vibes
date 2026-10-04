"""Servidor MCP de exemplo: o ERP de uma empresa cliente (pedidos de compra e fornecedores), só para o ambiente local
e os testes. Fala MCP por Streamable HTTP (revisão 2025-11-25), em JSON, e exige o token no cabeçalho Authorization.

No compose (perfil local): http://mcp-erp:8000/mcp, token MCP_ERP_TOKEN (padrão erp-dev-token). GET /chamadas devolve
as chamadas de ferramenta recebidas (para conferir que o agente consultou o ERP). Nos testes, responder() atende sem
rede.

Rodar sozinho: python tests/mcp_erp.py   (porta 8000)
"""
import json
import os
import re
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

TOKEN = os.environ.get("MCP_ERP_TOKEN", "erp-dev-token")
PEDIDOS = {
    "12345678000190": [{"numero": "PC-1001", "fornecedor": "Moinho Sul Ltda", "valor": 7200.00, "status": "aberto"}],
    "45678901000123": [{"numero": "PC-2001", "fornecedor": "Leite Bom Ltda", "valor": 1850.00, "status": "aberto"}],
    "98765432000110": [{"numero": "PC-3001", "fornecedor": "Grafica Lavras", "valor": 900.00, "status": "aberto"}],
}
FORNECEDORES = {
    "12345678000190": {"razao_social": "Moinho Sul Ltda", "situacao": "ativo", "conta_contabil": "3.1.02 Matéria-prima"},
    "45678901000123": {"razao_social": "Leite Bom Ltda", "situacao": "ativo", "conta_contabil": "3.1.01 Leite"},
    "98765432000110": {"razao_social": "Grafica Lavras", "situacao": "bloqueado", "conta_contabil": "3.3.05 Embalagens"},
}
FERRAMENTAS = [
    {
        "name": "consultar_pedido",
        "title": "Pedidos de compra",
        "description": "Pedidos de compra abertos de um fornecedor no ERP, pelo CNPJ: número, valor e status.",
        "inputSchema": {"type": "object", "properties": {"cnpj": {"type": "string", "description": "CNPJ do fornecedor"}},
                        "required": ["cnpj"]},
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "consultar_fornecedor",
        "title": "Fornecedor",
        "description": "Cadastro do fornecedor no ERP, pelo CNPJ: razão social, situação e conta contábil padrão.",
        "inputSchema": {"type": "object", "properties": {"cnpj": {"type": "string", "description": "CNPJ do fornecedor"}},
                        "required": ["cnpj"]},
        "annotations": {"readOnlyHint": True},
    },
]
chamadas: list[dict[str, Any]] = []


def responder(corpo: dict[str, Any], cabecalhos: dict[str, str]) -> tuple[int, dict[str, str], bytes]:
    """Uma mensagem JSON-RPC → (status, cabeçalhos, corpo). Sem o token certo, 401."""
    if {k.lower(): v for k, v in cabecalhos.items()}.get("authorization") != f"Bearer {TOKEN}":
        return 401, {"Content-Type": "application/json"}, b'{"error": "token"}'
    metodo, ident, params = corpo.get("method"), corpo.get("id"), corpo.get("params") or {}
    if ident is None:  # notificação (ex.: notifications/initialized)
        return 202, {}, b""
    extra: dict[str, str] = {}
    if metodo == "initialize":
        extra["Mcp-Session-Id"] = uuid.uuid4().hex
        resultado: dict[str, Any] = {"protocolVersion": params.get("protocolVersion") or "2025-11-25",
                                     "capabilities": {"tools": {}}, "serverInfo": {"name": "erp-exemplo", "version": "1.0"}}
    elif metodo == "tools/list":
        resultado = {"tools": FERRAMENTAS}
    elif metodo == "tools/call":
        nome, argumentos = params.get("name"), params.get("arguments") or {}
        chamadas.append({"ferramenta": nome, "argumentos": argumentos})
        cnpj = re.sub(r"\D", "", str(argumentos.get("cnpj", "")))
        if nome == "consultar_pedido":
            dados: Any = {"cnpj": cnpj, "pedidos": PEDIDOS.get(cnpj, [])}
        elif nome == "consultar_fornecedor":
            dados = FORNECEDORES.get(cnpj) or {"erro": "fornecedor não cadastrado"}
        else:
            return _json(200, extra, {"jsonrpc": "2.0", "id": ident, "error": {"code": -32602, "message": "ferramenta desconhecida"}})
        resultado = {"content": [{"type": "text", "text": json.dumps(dados, ensure_ascii=False)}], "structuredContent": dados}
    elif metodo == "ping":
        resultado = {}
    else:
        return _json(200, extra, {"jsonrpc": "2.0", "id": ident, "error": {"code": -32601, "message": "método desconhecido"}})
    return _json(200, extra, {"jsonrpc": "2.0", "id": ident, "result": resultado})


def _json(status: int, extra: dict[str, str], corpo: dict[str, Any]) -> tuple[int, dict[str, str], bytes]:
    return status, {"Content-Type": "application/json", **extra}, json.dumps(corpo, ensure_ascii=False).encode()


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - nome do http.server
        tamanho = int(self.headers.get("Content-Length") or 0)
        try:
            corpo = json.loads(self.rfile.read(tamanho) or b"{}")
        except json.JSONDecodeError:
            corpo = {}
        status, cabecalhos, resposta = responder(corpo, dict(self.headers.items()))
        self._enviar(status, cabecalhos, resposta)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/chamadas":
            self._enviar(200, {"Content-Type": "application/json"}, json.dumps(chamadas, ensure_ascii=False).encode())
        else:
            self._enviar(200 if self.path == "/saude" else 405, {}, b"")

    def do_DELETE(self) -> None:  # noqa: N802 - o cliente encerra a sessão
        self._enviar(200, {}, b"")

    def _enviar(self, status: int, cabecalhos: dict[str, str], corpo: bytes) -> None:
        self.send_response(status)
        for chave, valor in cabecalhos.items():
            self.send_header(chave, valor)
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def log_message(self, *args: Any) -> None:
        return None


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8000"))), _Handler).serve_forever()  # noqa: S104 - rede do compose
