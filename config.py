"""Configurações centrais: lê o .env e cria a conexão com suporte a banco local leve em Python."""
import hashlib
import json
import math
import os
import re
from pathlib import Path

from dotenv import load_dotenv

PASTA = Path(__file__).parent
load_dotenv(PASTA / ".env")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
MODELO_CLAUDE = os.getenv("MODELO_CLAUDE", "claude-haiku-5-5").strip()
CHROMA_MODO = os.getenv("CHROMA_MODO", "local").strip().lower()
EMBEDDING = os.getenv("EMBEDDING", "padrao").strip().lower()
SENHA_PROFESSOR = os.getenv("SENHA_PROFESSOR", "").strip()

PASTA_DADOS = PASTA / "dados"
PASTA_CHROMA = PASTA_DADOS / "chroma"
ARQUIVO_REGISTROS = PASTA_DADOS / "registros.db"
PASTA_APOSTILAS = PASTA / "materiais" / "apostilas"
PASTA_SLIDES = PASTA / "materiais" / "slides"

COLECAO_APOSTILAS = "apostilas"
COLECAO_SLIDES = "slides"

MODULOS = {
    "geral": "Geral",
    "68": "Reforço (OLITEF)",
    "69": "O Dinheiro e a Economia",
    "70": "Matemática Financeira e Planejamento",
    "71": "A Renda Fixa e seus Indicadores",
}

try:
    import chromadb
    from chromadb.utils import embedding_functions
    TEM_CHROMADB = True
except ImportError:
    TEM_CHROMADB = False


class MicroVectorStore:
    """Banco vetorial leve em Python puro para evitar compilação C++."""
    def __init__(self, filepath: Path):
        self.filepath = filepath
        self.data = []
        self.load()

    def load(self):
        if self.filepath.exists():
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except Exception:
                self.data = []

    def save(self):
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def count(self) -> int:
        return len(self.data)

    def delete(self, where: dict = None):
        if not where:
            self.data = []
        else:
            def matches(item_meta):
                for k, v in where.items():
                    if item_meta.get(k) != v:
                        return False
                return True
            self.data = [item for item in self.data if not matches(item.get("metadata", {}))]
        self.save()

    def upsert(self, ids, documents, metadatas):
        id_map = {item["id"]: i for i, item in enumerate(self.data)}
        for id_, doc, meta in zip(ids, documents, metadatas):
            item = {"id": id_, "document": doc, "metadata": meta}
            if id_ in id_map:
                self.data[id_map[id_]] = item
            else:
                self.data.append(item)
                id_map[id_] = len(self.data) - 1
        self.save()

    def get(self, include=None):
        return {"metadatas": [item["metadata"] for item in self.data]}

    def _tokenize(self, text):
        return set(re.findall(r'\w+', text.lower()))

    def query(self, query_texts, n_results=4, where=None):
        query_text = query_texts[0] if query_texts else ""
        q_tokens = self._tokenize(query_text)

        candidates = self.data
        if where:
            filtered = []
            for item in candidates:
                meta = item.get("metadata", {})
                match = True
                for k, v in where.items():
                    if isinstance(v, dict) and "$in" in v:
                        if meta.get(k) not in v["$in"]:
                            match = False
                            break
                    elif meta.get(k) != v:
                        match = False
                        break
                if match:
                    filtered.append(item)
            candidates = filtered

        scored = []
        for item in candidates:
            doc_tokens = self._tokenize(item["document"])
            if not doc_tokens or not q_tokens:
                score = 0.0
            else:
                intersection = q_tokens.intersection(doc_tokens)
                score = len(intersection) / (math.sqrt(len(q_tokens)) * math.sqrt(len(doc_tokens)))
            dist = 1.0 - score
            scored.append((dist, item))

        scored.sort(key=lambda x: x[0])
        top_n = scored[:n_results]

        return {
            "documents": [[item["document"] for _, item in top_n]],
            "metadatas": [[item["metadata"] for _, item in top_n]],
            "distances": [[dist for dist, _ in top_n]]
        }


class ClienteLocalPython:
    def delete_collection(self, nome: str):
        p = PASTA_CHROMA / f"{nome}.json"
        if p.exists():
            p.unlink()


def cliente_chroma():
    if TEM_CHROMADB:
        if CHROMA_MODO == "cloud":
            return chromadb.CloudClient(
                api_key=os.getenv("CHROMA_API_KEY"),
                tenant=os.getenv("CHROMA_TENANT"),
                database=os.getenv("CHROMA_DATABASE"),
            )
        PASTA_CHROMA.mkdir(parents=True, exist_ok=True)
        return chromadb.PersistentClient(path=str(PASTA_CHROMA))
    return ClienteLocalPython()


def colecao(nome: str):
    if TEM_CHROMADB:
        def funcao_embedding():
            if EMBEDDING == "teste":
                return EmbeddingTeste()
            if EMBEDDING == "multilingue":
                return embedding_functions.SentenceTransformerEmbeddingFunction(
                    model_name="paraphrase-multilingual-MiniLM-L12-v2"
                )
            return embedding_functions.DefaultEmbeddingFunction()
            
        return cliente_chroma().get_or_createcollection(
            name=nome,
            embedding_function=funcao_embedding(),
            metadata={"hnsw:space": "cosine"},
        )
    else:
        PASTA_CHROMA.mkdir(parents=True, exist_ok=True)
        return MicroVectorStore(PASTA_CHROMA / f"{nome}.json")