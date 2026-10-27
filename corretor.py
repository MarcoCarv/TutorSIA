"""Corretor: busca o material relevante e pede à IA (Gemini grátis ou Claude) para corrigir.

Isto é RAG (Retrieval-Augmented Generation): a IA não é 'treinada' de novo.
A cada correção, buscamos os trechos mais parecidos com a pergunta e mandamos
junto, com a instrução de corrigir APENAS com base neles.
"""
import json
import os
import re
import time
import urllib.error
import urllib.request

import config

# Gemini (Google): chave gratuita em aistudio.google.com, sem cartão de crédito.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
MODELO_GEMINI = os.getenv("MODELO_GEMINI", "gemini-flash-latest").strip()

TRECHOS_POR_COLECAO = 4

INSTRUCOES = """Você é o corretor do app SIA, de educação financeira para alunos do ensino médio.
Corrija a resposta do aluno usando APENAS os TRECHOS DE REFERÊNCIA e os PONTOS-CHAVE
do gabarito. Não use conhecimento de fora. Se os trechos não cobrirem a pergunta,
diga isso em "o_que_faltou" e marque confianca = "baixa".

Regras:
- Avalie o raciocínio e os conceitos, não a ortografia nem o tamanho do texto.
- Respostas com outras palavras, mas conceitualmente certas, valem nota cheia.
- Nota de 0 a 10 (inteiro). 8-10 = correta; 4-7 = parcialmente correta; 0-3 = incorreta.
- Escreva para um adolescente: frases curtas, tom encorajador e direto, sem jargão.
- "dica" é uma pergunta-guia que faz o aluno pensar SEM entregar a resposta.
- "explicacao_completa" explica a resposta certa em até 4 frases, citando o conceito.
- Em "fontes_usadas", liste os números dos trechos que você realmente usou.
- Se a resposta for cópia literal de um trecho, aceite o conteúdo, mas diga no
  feedback para o aluno explicar com as próprias palavras."""

FERRAMENTA = {
    "name": "registrar_correcao",
    "description": "Registra a correção estruturada da resposta do aluno.",
    "input_schema": {
        "type": "object",
        "properties": {
            "nota": {"type": "integer", "minimum": 0, "maximum": 10},
            "veredito": {"type": "string",
                         "enum": ["correta", "parcialmente_correta", "incorreta"]},
            "o_que_acertou": {"type": "string"},
            "o_que_faltou": {"type": "string"},
            "dica": {"type": "string"},
            "explicacao_completa": {"type": "string"},
            "fontes_usadas": {"type": "array", "items": {"type": "integer"}},
            "confianca": {"type": "string", "enum": ["alta", "media", "baixa"]},
        },
        "required": ["nota", "veredito", "o_que_acertou", "o_que_faltou", "dica",
                     "explicacao_completa", "fontes_usadas", "confianca"],
    },
}


def buscar_trechos(texto_busca: str, modulo: str | None = None):
    """Busca nas duas coleções (apostilas e slides) os trechos mais parecidos."""
    resultados = []
    for nome in (config.COLECAO_APOSTILAS, config.COLECAO_SLIDES):
        col = config.colecao(nome)
        if col.count() == 0:
            continue
        filtro = {"modulo": {"$in": [modulo, "geral"]}} if modulo and modulo != "geral" else None
        n = min(TRECHOS_POR_COLECAO, col.count())
        r = col.query(query_texts=[texto_busca], n_results=n, where=filtro)
        if filtro and not r["documents"][0]:  # nada no módulo? busca em tudo
            r = col.query(query_texts=[texto_busca], n_results=n)
        for doc, meta, dist in zip(r["documents"][0], r["metadatas"][0], r["distances"][0]):
            resultados.append({"texto": doc, "fonte": meta["fonte"], "pagina": meta["pagina"],
                               "tipo": meta.get("tipo", nome), "distancia": round(dist, 3)})
    resultados.sort(key=lambda x: x["distancia"])
    return resultados[: TRECHOS_POR_COLECAO + 2]


def montar_mensagem(pergunta: str, resposta: str, trechos, pontos_chave=None) -> str:
    refs = "\n\n".join(
        f"[Trecho {i + 1}] ({t['tipo']}: {t['fonte']}, p. {t['pagina']})\n{t['texto']}"
        for i, t in enumerate(trechos)
    ) or "(nenhum trecho encontrado)"
    gabarito = "\n".join(f"- {p}" for p in (pontos_chave or [])) or "(sem gabarito; use os trechos)"
    return (f"TRECHOS DE REFERÊNCIA:\n{refs}\n\n"
            f"PERGUNTA:\n{pergunta}\n\n"
            f"PONTOS-CHAVE DO GABARITO:\n{gabarito}\n\n"
            f"RESPOSTA DO ALUNO:\n{resposta}")


def chamar_claude(mensagem: str) -> dict:
    if not config.ANTHROPIC_API_KEY or config.ANTHROPIC_API_KEY.startswith("cole-"):
        raise RuntimeError("Falta a ANTHROPIC_API_KEY no arquivo .env (veja o README, passo 3).")
    import anthropic
    cliente = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    resp = cliente.messages.create(
        model=config.MODELO_CLAUDE,
        max_tokens=1000,
        system=INSTRUCOES,
        tools=[FERRAMENTA],
        tool_choice={"type": "tool", "name": "registrar_correcao"},
        messages=[{"role": "user", "content": mensagem}],
    )
    for bloco in resp.content:
        if bloco.type == "tool_use":
            return dict(bloco.input)
    raise RuntimeError("O modelo não devolveu a correção no formato esperado.")


def _esquema_gemini(esq: dict) -> dict:
    """Converte o esquema da ferramenta do Claude para o formato que o Gemini aceita."""
    tipos = {"object": "OBJECT", "string": "STRING", "integer": "INTEGER", "array": "ARRAY"}
    novo = {"type": tipos[esq["type"]]}
    if "enum" in esq:
        novo["enum"] = esq["enum"]
    if "properties" in esq:
        novo["properties"] = {k: _esquema_gemini(v) for k, v in esq["properties"].items()}
    if "required" in esq:
        novo["required"] = esq["required"]
    if "items" in esq:
        novo["items"] = _esquema_gemini(esq["items"])
    return novo


def chamar_gemini(mensagem: str) -> dict:
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{MODELO_GEMINI}:generateContent")
    corpo = json.dumps({
        "system_instruction": {"parts": [{"text": INSTRUCOES}]},
        "contents": [{"role": "user", "parts": [{"text": mensagem}]}],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json",
            "responseSchema": _esquema_gemini(FERRAMENTA["input_schema"]),
        },
    }).encode("utf-8")
    pedido = urllib.request.Request(url, data=corpo, method="POST", headers={
        "Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY})
    for tentativa in range(2):
        try:
            with urllib.request.urlopen(pedido, timeout=60) as r:
                dados = json.loads(r.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as e:
            if e.code == 429:
                raise RuntimeError("Muita gente usando o tutor agora. Espere um minuto e tente de novo.")
            if e.code in (500, 503) and tentativa == 0:
                time.sleep(2)
                continue
            raise RuntimeError(f"O Gemini recusou o pedido (erro {e.code}).")
    try:
        texto = dados["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(texto)
    except (KeyError, IndexError, json.JSONDecodeError):
        raise RuntimeError("O modelo não devolveu a correção no formato esperado.")


def _normalizar(c: dict) -> dict:
    """Garante que a correção tenha todos os campos que o app usa."""
    try:
        nota = max(0, min(10, int(round(float(c.get("nota", 0))))))
    except (TypeError, ValueError):
        nota = 0
    c["nota"] = nota
    if c.get("veredito") not in ("correta", "parcialmente_correta", "incorreta"):
        c["veredito"] = "correta" if nota >= 8 else "parcialmente_correta" if nota >= 4 else "incorreta"
    if c.get("confianca") not in ("alta", "media", "baixa"):
        c["confianca"] = "media"
    for campo in ("o_que_acertou", "o_que_faltou", "dica", "explicacao_completa"):
        c[campo] = str(c.get(campo) or "")
    fontes = []
    for f in c.get("fontes_usadas") or []:
        try:
            fontes.append(int(f))
        except (TypeError, ValueError):
            pass
    c["fontes_usadas"] = fontes
    return c


def chamar_ia(mensagem: str) -> dict:
    """Usa o Gemini (grátis) se houver GEMINI_API_KEY; senão, o Claude."""
    if GEMINI_API_KEY:
        return chamar_gemini(mensagem)
    if config.ANTHROPIC_API_KEY and not config.ANTHROPIC_API_KEY.startswith("cole-"):
        return chamar_claude(mensagem)
    raise RuntimeError("Falta a chave da IA: configure GEMINI_API_KEY (grátis) ou ANTHROPIC_API_KEY.")


def resumo(texto: str, limite: int = 280) -> str:
    """Trecho curto e sem marcações de Markdown, para mostrar ao aluno."""
    limpo = re.sub(r"[#*>]+", "", texto)
    limpo = re.sub(r"\s+", " ", limpo).strip()
    return limpo[:limite] + ("…" if len(limpo) > limite else "")


def corrigir(pergunta: str, resposta: str, modulo: str | None = None,
             pontos_chave=None, _llm=None) -> dict:
    """Função principal. _llm permite trocar o Claude por um simulador nos testes."""
    trechos = buscar_trechos(pergunta + " " + " ".join(pontos_chave or []), modulo)
    correcao = _normalizar((_llm or chamar_ia)(montar_mensagem(pergunta, resposta, trechos, pontos_chave)))
    usados = set(correcao.get("fontes_usadas") or [])
    correcao["fontes"] = [
        {"numero": i + 1, "fonte": t["fonte"], "pagina": t["pagina"], "tipo": t["tipo"],
         "trecho": resumo(t["texto"])}
        for i, t in enumerate(trechos) if (i + 1) in usados
    ]
    return correcao


if __name__ == "__main__":
    # Teste rápido pelo terminal: python corretor.py
    p = "O que acontece com o poder de compra quando a inflação sobe?"
    for t in buscar_trechos(p, "69"):
        print(f"{t['distancia']:.3f}  {t['fonte']} p.{t['pagina']}: {t['texto'][:90]}...")
