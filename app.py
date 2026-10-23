"""API do Tutor SIA. Rode com:  uvicorn app:app --reload
Depois abra http://127.0.0.1:8000  (documentação automática em /docs)
"""
import json
import shutil
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

import config
import corretor
import ingestao

app = FastAPI(title="Tutor SIA", description="Correção de respostas abertas com RAG + Chroma")
PERGUNTAS = json.loads((config.PASTA / "perguntas.json").read_text(encoding="utf-8"))
POR_ID = {p["id"]: p for p in PERGUNTAS}
MIN_CARACTERES = 20


# ---------- banco de registros (SQLite): o que faltou medir no datathon ----------
def db():
    config.PASTA_DADOS.mkdir(exist_ok=True)
    con = sqlite3.connect(config.ARQUIVO_REGISTROS)
    con.execute("""CREATE TABLE IF NOT EXISTS tentativas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, criado_em TEXT, aluno_id TEXT,
        pergunta_id TEXT, modulo TEXT, resposta TEXT, tempo_segundos REAL,
        colou_texto INTEGER, tentativa_numero INTEGER, nota INTEGER,
        veredito TEXT, confianca TEXT, fontes TEXT)""")
    return con


# ---------- modelos de entrada ----------
class PedidoCorrecao(BaseModel):
    aluno_id: str
    pergunta_id: str | None = None
    pergunta_livre: str | None = None   # para perguntas fora do banco
    modulo: str | None = None
    resposta: str
    tempo_segundos: float | None = None
    colou_texto: bool = False


# ---------- rotas do aluno ----------
@app.get("/")
def pagina():
    return FileResponse(config.PASTA / "static" / "index.html")


@app.get("/perguntas")
def listar_perguntas(modulo: str | None = None):
    lista = [p for p in PERGUNTAS if not modulo or p["modulo"] == modulo]
    # o gabarito NÃO vai para o aluno
    return [{k: p[k] for k in ("id", "modulo", "nivel", "pergunta")} for p in lista]


@app.get("/modulos")
def listar_modulos():
    return config.MODULOS


@app.post("/corrigir")
def corrigir(pedido: PedidoCorrecao):
    resposta = pedido.resposta.strip()
    if len(resposta) < MIN_CARACTERES:
        raise HTTPException(422, f"Explique com suas palavras (mínimo de {MIN_CARACTERES} caracteres).")

    if pedido.pergunta_id:
        if pedido.pergunta_id not in POR_ID:
            raise HTTPException(404, "Pergunta não encontrada.")
        q = POR_ID[pedido.pergunta_id]
        pergunta, modulo, pontos = q["pergunta"], q["modulo"], q.get("pontos_chave")
    elif pedido.pergunta_livre:
        pergunta, modulo, pontos = pedido.pergunta_livre, pedido.modulo, None
    else:
        raise HTTPException(422, "Envie pergunta_id ou pergunta_livre.")

    con = db()
    anteriores = con.execute("SELECT COUNT(*) FROM tentativas WHERE aluno_id=? AND pergunta_id=?",
                             (pedido.aluno_id, pedido.pergunta_id or pergunta[:60])).fetchone()[0]
    tentativa = anteriores + 1

    try:
        c = corretor.corrigir(pergunta, resposta, modulo, pontos)
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    except Exception as e:  # erro de rede, chave inválida, modelo errado etc.
        raise HTTPException(503, f"Não consegui falar com o Claude: {e}")

    # Pedagogia: na 1ª tentativa errada o aluno recebe só a dica; a explicação completa
    # aparece quando ele acerta ou a partir da 2ª tentativa (erro vira aprendizado, não chute).
    liberar = c["nota"] >= 8 or tentativa >= 2
    c["explicacao_liberada"] = liberar
    if not liberar:
        c["explicacao_completa"] = None
    c["tentativa_numero"] = tentativa
    c["resposta_rapida"] = bool(pedido.tempo_segundos is not None and pedido.tempo_segundos < 15)

    con.execute("""INSERT INTO tentativas (criado_em, aluno_id, pergunta_id, modulo, resposta,
        tempo_segundos, colou_texto, tentativa_numero, nota, veredito, confianca, fontes)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (datetime.now().isoformat(timespec="seconds"), pedido.aluno_id,
         pedido.pergunta_id or pergunta[:60], modulo, resposta, pedido.tempo_segundos,
         int(pedido.colou_texto), tentativa, c["nota"], c["veredito"], c["confianca"],
         json.dumps([f"{f['fonte']} p.{f['pagina']}" for f in c["fontes"]], ensure_ascii=False)))
    con.commit()
    con.close()
    return c


# ---------- rotas do professor ----------
def checar_senha(senha: str | None):
    if config.SENHA_PROFESSOR and senha != config.SENHA_PROFESSOR:
        raise HTTPException(401, "Senha do professor incorreta.")


@app.post("/professor/slides")
async def enviar_slides(arquivo: UploadFile = File(...), modulo: str = Form("geral"),
                        turma: str = Form("todas"), x_senha: str | None = Header(None)):
    checar_senha(x_senha)
    nome = Path(arquivo.filename or "slides.pdf").name
    if Path(nome).suffix.lower() not in (".pdf", ".md", ".txt"):
        raise HTTPException(415, "Envie um PDF (ou .md/.txt).")
    config.PASTA_SLIDES.mkdir(parents=True, exist_ok=True)
    destino = config.PASTA_SLIDES / nome
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(nome).suffix) as tmp:
        shutil.copyfileobj(arquivo.file, tmp)
    shutil.move(tmp.name, destino)
    n = ingestao.indexar_arquivo(destino, config.COLECAO_SLIDES, modulo, turma, nome)
    if n == 0:
        raise HTTPException(422, "Não encontrei texto no PDF. Ele pode ser só imagem (escaneado).")
    return {"arquivo": nome, "trechos": n, "modulo": modulo, "turma": turma}


@app.get("/professor/materiais")
def materiais():
    saida = {}
    for nome in (config.COLECAO_APOSTILAS, config.COLECAO_SLIDES):
        dados = config.colecao(nome).get(include=["metadatas"])
        fontes = {}
        for m in dados["metadatas"]:
            f = fontes.setdefault(m["fonte"], {"fonte": m["fonte"], "modulo": m["modulo"], "trechos": 0})
            f["trechos"] += 1
        saida[nome] = sorted(fontes.values(), key=lambda x: x["fonte"])
    return saida


@app.delete("/professor/slides/{nome}")
def apagar_slides(nome: str, x_senha: str | None = Header(None)):
    checar_senha(x_senha)
    config.colecao(config.COLECAO_SLIDES).delete(where={"fonte": nome})
    (config.PASTA_SLIDES / Path(nome).name).unlink(missing_ok=True)
    return {"apagado": nome}


@app.get("/metricas")
def metricas():
    """Os indicadores que provariam se a funcionalidade funcionou (ver pitch)."""
    con = db()
    q = lambda sql: con.execute(sql).fetchone()
    total, alunos = q("SELECT COUNT(*), COUNT(DISTINCT aluno_id) FROM tentativas")
    nota1 = q("SELECT AVG(nota) FROM tentativas WHERE tentativa_numero=1")[0]
    rapidas = q("SELECT AVG(tempo_segundos < 15) FROM tentativas WHERE tempo_segundos IS NOT NULL")[0]
    coladas = q("SELECT AVG(colou_texto) FROM tentativas")[0]
    # ganho de quem errou e tentou de novo: nota da 2ª tentativa - nota da 1ª
    ganho = q("""SELECT AVG(b.nota - a.nota) FROM tentativas a JOIN tentativas b
                 ON a.aluno_id=b.aluno_id AND a.pergunta_id=b.pergunta_id
                 AND a.tentativa_numero=1 AND b.tentativa_numero=2""")[0]
    por_pergunta = [dict(zip(("pergunta_id", "tentativas", "nota_media"), r)) for r in con.execute(
        "SELECT pergunta_id, COUNT(*), ROUND(AVG(nota),1) FROM tentativas GROUP BY pergunta_id ORDER BY 3")]
    con.close()
    r = lambda x, k=1: round(x, k) if x is not None else None
    return {"tentativas": total, "alunos": alunos, "nota_media_1a_tentativa": r(nota1),
            "pct_respostas_rapidas": r(rapidas * 100 if rapidas is not None else None),
            "pct_texto_colado": r(coladas * 100 if coladas is not None else None),
            "ganho_medio_1a_para_2a": r(ganho), "por_pergunta": por_pergunta}
