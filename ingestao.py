"""Ingestão: transforma apostilas e slides em trechos pesquisáveis no Chroma.

Uso pelo terminal:
    python ingestao.py                      # indexa tudo de materiais/apostilas
    python ingestao.py --pasta materiais/slides --colecao slides --modulo 70
    python ingestao.py --listar             # mostra o que já está no banco
    python ingestao.py --zerar              # apaga as coleções e começa do zero
"""
import argparse
import hashlib
import re
from pathlib import Path

from pypdf import PdfReader

import config

TAMANHO_TRECHO = 900   # caracteres por trecho
SOBREPOSICAO = 150     # repete um pedaço do trecho anterior para não cortar ideias


def ler_paginas(caminho: Path):
    """Devolve lista de (numero_da_pagina, texto). Para .md/.txt a 'página' é 1."""
    sufixo = caminho.suffix.lower()
    if sufixo == ".pdf":
        leitor = PdfReader(str(caminho))
        return [(i + 1, p.extract_text() or "") for i, p in enumerate(leitor.pages)]
    if sufixo in (".md", ".txt"):
        return [(1, caminho.read_text(encoding="utf-8"))]
    raise ValueError(f"Formato não suportado: {caminho.name} (use PDF, MD ou TXT)")


def limpar(texto: str) -> str:
    texto = texto.replace("\x00", " ")
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


def sobra(trecho: str) -> str:
    """Final do trecho anterior, começando numa frase (ou palavra) inteira."""
    fim = trecho[-SOBREPOSICAO:]
    m = re.search(r"[.!?:]\**\s+|\n", fim)
    if m:
        return fim[m.end():].strip()
    i = fim.find(" ")
    return fim[i + 1:].strip() if i != -1 else fim


def dividir(texto: str):
    """Divide o texto em trechos de ~TAMANHO_TRECHO, respeitando parágrafos."""
    paragrafos = [p.strip() for p in texto.split("\n\n") if p.strip()]
    trechos, atual = [], ""
    for p in paragrafos:
        if len(atual) + len(p) + 2 <= TAMANHO_TRECHO:
            atual = f"{atual}\n\n{p}" if atual else p
            continue
        if atual:
            trechos.append(atual)
        while len(p) > TAMANHO_TRECHO:  # parágrafo gigante (comum em PDF)
            corte = p.rfind(" ", 0, TAMANHO_TRECHO) or TAMANHO_TRECHO
            trechos.append(p[:corte])
            p = sobra(p[:corte]) + " " + p[corte:].strip()
        atual = (sobra(trechos[-1]) + " " + p) if trechos else p
    if atual:
        trechos.append(atual)
    return [t for t in trechos if len(t) > 40]


def modulo_pelo_nome(nome: str) -> str:
    """Arquivos que começam com o ID do módulo (ex.: '70_juros.pdf') ganham esse módulo."""
    m = re.match(r"(6[89]|7[01])[_\- ]", nome)
    return m.group(1) if m else "geral"


def indexar_arquivo(caminho: Path, nome_colecao: str, modulo: str | None = None,
                    turma: str = "todas", nome_original: str | None = None) -> int:
    col = config.colecao(nome_colecao)
    fonte = nome_original or caminho.name
    modulo = modulo or modulo_pelo_nome(fonte)
    ids, docs, metas = [], [], []
    for pagina, texto in ler_paginas(caminho):
        for i, trecho in enumerate(dividir(limpar(texto))):
            chave = hashlib.sha1(f"{fonte}|{pagina}|{i}".encode()).hexdigest()[:16]
            ids.append(chave)
            docs.append(trecho)
            metas.append({"fonte": fonte, "pagina": pagina, "modulo": modulo,
                          "turma": str(turma), "tipo": nome_colecao})
    if not docs:
        print(f"  ! {fonte}: nenhum texto encontrado (PDF escaneado? veja o README)")
        return 0
    # Remove versões antigas do mesmo arquivo e grava as novas (evita duplicatas)
    col.delete(where={"fonte": fonte})
    for ini in range(0, len(docs), 100):
        col.upsert(ids=ids[ini:ini + 100], documents=docs[ini:ini + 100],
                   metadatas=metas[ini:ini + 100])
    print(f"  ✓ {fonte}: {len(docs)} trechos (módulo {modulo})")
    return len(docs)


def indexar_pasta(pasta: Path, nome_colecao: str, modulo: str | None = None) -> int:
    arquivos = sorted(p for p in pasta.glob("*") if p.suffix.lower() in (".pdf", ".md", ".txt"))
    if not arquivos:
        print(f"Nenhum PDF/MD/TXT em {pasta}")
        return 0
    print(f"Indexando {len(arquivos)} arquivo(s) de {pasta} na coleção '{nome_colecao}'...")
    return sum(indexar_arquivo(a, nome_colecao, modulo) for a in arquivos)


def listar():
    for nome in (config.COLECAO_APOSTILAS, config.COLECAO_SLIDES):
        col = config.colecao(nome)
        dados = col.get(include=["metadatas"])
        fontes = {}
        for m in dados["metadatas"]:
            fontes[m["fonte"]] = fontes.get(m["fonte"], 0) + 1
        print(f"\nColeção '{nome}': {col.count()} trechos")
        for f, n in sorted(fontes.items()):
            print(f"  - {f}: {n} trechos")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pasta", default=str(config.PASTA_APOSTILAS))
    ap.add_argument("--colecao", default=config.COLECAO_APOSTILAS)
    ap.add_argument("--modulo", default=None, help="68, 69, 70, 71 ou geral")
    ap.add_argument("--listar", action="store_true")
    ap.add_argument("--zerar", action="store_true")
    a = ap.parse_args()
    if a.zerar:
        cli = config.cliente_chroma()
        for nome in (config.COLECAO_APOSTILAS, config.COLECAO_SLIDES):
            try:
                cli.delete_collection(nome)
                print(f"Coleção '{nome}' apagada.")
            except Exception:
                pass
    elif a.listar:
        listar()
    else:
        total = indexar_pasta(Path(a.pasta), a.colecao, a.modulo)
        print(f"Pronto: {total} trechos gravados.")
