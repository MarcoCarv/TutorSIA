"""Corretor: busca o material relevante no Chroma e pede ao Claude para corrigir.

Isto é RAG (Retrieval-Augmented Generation): a IA não é 'treinada' de novo.
A cada correção, buscamos os trechos mais parecidos com a pergunta e mandamos
junto, com a instrução de corrigir APENAS com base neles.
"""
import re

import config

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


def resumo(texto: str, limite: int = 280) -> str:
    """Trecho curto e sem marcações de Markdown, para mostrar ao aluno."""
    limpo = re.sub(r"[#*>]+", "", texto)
    limpo = re.sub(r"\s+", " ", limpo).strip()
    return limpo[:limite] + ("…" if len(limpo) > limite else "")


def corrigir(pergunta: str, resposta: str, modulo: str | None = None,
             pontos_chave=None, _llm=None) -> dict:
    """Função principal. _llm permite trocar o Claude por um simulador nos testes."""
    trechos = buscar_trechos(pergunta + " " + " ".join(pontos_chave or []), modulo)
    correcao = (_llm or chamar_claude)(montar_mensagem(pergunta, resposta, trechos, pontos_chave))
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
