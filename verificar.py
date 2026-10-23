"""Checa se está tudo pronto. Rode:  python verificar.py"""
import sys

import config

ok = True
def item(passou, texto, ajuda=""):
    global ok
    ok &= passou
    print(("  [OK] " if passou else "  [FALTA] ") + texto + ("" if passou else f"\n         -> {ajuda}"))

print("Verificando o Tutor SIA...\n")
item(sys.version_info >= (3, 10), f"Python {sys.version.split()[0]}", "instale o Python 3.11 ou 3.12")
item(bool(config.ANTHROPIC_API_KEY) and not config.ANTHROPIC_API_KEY.startswith("cole-"),
     "Chave do Claude no .env", "copie .env.example para .env e cole sua ANTHROPIC_API_KEY")
try:
    n = config.colecao(config.COLECAO_APOSTILAS).count()
    item(n > 0, f"Chroma ({config.CHROMA_MODO}) com {n} trechos de apostila", "rode: python ingestao.py")
except Exception as e:
    item(False, "Conexão com o Chroma", str(e))

if ok:
    print("\nTestando uma correção de verdade com o Claude...")
    import corretor
    r = corretor.corrigir("Quais são as três funções do dinheiro?",
                          "Serve para trocar por coisas, para comparar preços e para guardar.", "69")
    print(f"  Nota {r['nota']}/10 ({r['veredito']}). Fontes: {[f['fonte'] for f in r['fontes']]}")
    print("\nTudo certo! Agora rode:  uvicorn app:app --reload")
else:
    print("\nResolva os itens acima e rode de novo.")
