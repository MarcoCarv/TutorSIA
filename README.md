# Tutor SIA: correção de respostas abertas com IA + ChromaDB

O aluno responde uma pergunta **com as próprias palavras**. O tutor procura no material (apostilas e slides do professor) os trechos que tratam do assunto e pede ao Claude para corrigir **com base nesses trechos**. O aluno recebe uma nota, o que acertou, o que faltou, uma dica e as páginas de onde veio a correção.

## A ideia em uma frase (para o pitch)

No extrato da SIA, os alunos chutavam (46% das respostas em até 2 segundos), refaziam quiz até passar e abandonavam tentativas para trocar de pergunta. Uma pergunta aberta não se chuta, e cada resposta gera dados que hoje não existem: ID da pergunta, tempo real, texto colado e evolução entre tentativas.

## "Treinar a IA" x o que este projeto faz

A IA **não é treinada de novo**. Isso seria caro e lento. Usamos uma técnica chamada **RAG**:

1. As apostilas são cortadas em trechos e guardadas no **ChromaDB**, um banco que encontra textos **parecidos em significado** (não só com as mesmas palavras).
2. Quando o aluno responde, o sistema busca os trechos mais relevantes para aquela pergunta.
3. O Claude recebe a pergunta, os pontos-chave do gabarito, os trechos e a resposta, com a ordem de corrigir **só com base neles**.

Vantagem para a banca: se o professor enviar slides novos, o tutor passa a usá-los **na hora**, sem treino nenhum. E toda correção mostra a fonte, então dá para auditar.

## O que tem em cada arquivo

| Arquivo | Para que serve |
|---|---|
| `ingestao.py` | Lê PDFs/MD/TXT, divide em trechos e grava no Chroma |
| `corretor.py` | Busca os trechos e pede a correção ao Claude |
| `app.py` | A API (servidor) com as rotas do aluno, do professor e das métricas |
| `static/index.html` | A tela que vocês vão mostrar no pitch |
| `perguntas.json` | 18 perguntas abertas com gabarito em pontos-chave |
| `materiais/apostilas/` | Material dos 4 módulos (texto-exemplo escrito por nós; troquem ou somem com as apostilas oficiais) |
| `verificar.py` | Checa se está tudo configurado e faz uma correção de teste |
| `.env.example` | Modelo das configurações (chaves e opções) |

---

## Passo a passo (do zero)

### 1. Instale o Python

- Baixe o **Python 3.12** em https://www.python.org/downloads/
- **Windows:** na primeira tela do instalador, marque **"Add Python to PATH"** antes de clicar em Install.
- Para conferir, abra o terminal e digite `python --version` (no Mac: `python3 --version`).

> **Terminal**: no Windows, procure "PowerShell" no menu Iniciar. No Mac, abra o app "Terminal".

### 2. Abra a pasta do projeto no terminal e instale as dependências

Descompacte o `tutor_sia.zip`. No terminal, entre na pasta (troque pelo caminho real):

```bash
cd caminho/para/tutor_sia
```

Crie um "ambiente virtual" (uma caixinha isolada para as bibliotecas do projeto) e ative:

**Windows (PowerShell):**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```
Se aparecer erro de "execução de scripts desabilitada", rode uma vez `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, responda `S` e tente de novo.

**Mac/Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

Com o ambiente ativo (aparece `(.venv)` no começo da linha), instale:
```bash
pip install -r requirements.txt
```

### 3. Pegue a chave do Claude e crie o `.env`

1. Entre em https://console.anthropic.com, crie a conta, adicione créditos (o uso numa demo é baixo; confira os preços em https://docs.claude.com) e gere uma **API Key** em "API Keys".
2. Copie o arquivo `.env.example` e renomeie a cópia para `.env`.
   - Windows: `copy .env.example .env` / Mac: `cp .env.example .env`
3. Abra o `.env` num editor de texto (Bloco de Notas serve) e cole a chave em `ANTHROPIC_API_KEY=`.

**Nunca** coloque o `.env` em slides, GitHub ou grupo de WhatsApp: a chave é como uma senha com cartão de crédito.

### 4. Coloque o material e grave no Chroma

Os 4 arquivos de `materiais/apostilas/` já funcionam. Para usar apostilas reais, coloque os PDFs na mesma pasta. **Dica:** comece o nome do arquivo com o ID do módulo (`69_`, `70_`, `71_` ou `68_`) para o tutor saber de qual módulo é. Exemplo: `70_caderno_bcb_juros.pdf`. Sem o número, o arquivo vale para todos os módulos.

Boas fontes gratuitas para baixar: os cadernos de **Cidadania Financeira do Banco Central**, os materiais da **ENEF / Vida e Dinheiro**, o portal **CVM Educacional** e as páginas educativas do **Tesouro Direto**. Confiram as licenças de uso.

Depois rode:
```bash
python ingestao.py
```
Na primeira vez, o Chroma baixa um modelo de ~80 MB para transformar texto em vetores (só uma vez).

Comandos úteis:
```bash
python ingestao.py --listar    # mostra o que já está gravado
python ingestao.py --zerar     # apaga tudo para recomeçar
```
Rodar `python ingestao.py` de novo **não duplica** nada: arquivos já gravados são substituídos.

### 5. Verifique se está tudo certo

```bash
python verificar.py
```
Ele confere o Python, a chave, o Chroma e faz **uma correção real** de teste.

### 6. Ligue o servidor e abra no navegador

```bash
uvicorn app:app --reload
```
Abra **http://127.0.0.1:8000**. Para desligar, aperte `Ctrl + C` no terminal.

- Aba **Responder**: o aluno escolhe o módulo, escreve e recebe a correção.
- Aba **Professor**: envia o PDF dos slides, escolhe o módulo e a turma. Em segundos o tutor já usa esse material.
- Aba **Números**: os indicadores para provar que funcionou.
- **http://127.0.0.1:8000/docs**: a documentação automática da API, onde dá para testar cada rota clicando em "Try it out". Ótimo para mostrar à banca que é uma API de verdade.

---

## Usando o Chroma Cloud (opcional)

Comecem no modo local. Se quiserem mostrar na nuvem:

1. Crie a conta em https://trychroma.com e crie um **database**.
2. Copie a **API key**, o **tenant** e o nome do **database**.
3. No `.env`: `CHROMA_MODO=cloud` e preencha `CHROMA_API_KEY`, `CHROMA_TENANT` e `CHROMA_DATABASE`.
4. Rode `python ingestao.py` de novo (os dados vão para a nuvem).

Nada mais muda no código: só a linha que cria a conexão (`cliente_chroma()` em `config.py`).

## Opções no `.env`

- `MODELO_CLAUDE`: `claude-haiku-5-5` (rápido e barato, padrão) ou `claude-sonnet-5-5` (mais caprichado).
- `EMBEDDING`: `padrao` (já funciona), `multilingue` (melhor em português, mas exige `pip install sentence-transformers`, que baixa ~1 GB) ou `teste` (sem internet, qualidade ruim). **Se trocar o embedding, rode `python ingestao.py --zerar` e depois `python ingestao.py`.**
- `SENHA_PROFESSOR`: se preencher, o envio de slides passa a exigir essa senha.

## Como a correção funciona (regras pedagógicas)

- Resposta com menos de 20 caracteres não é corrigida: "explique com suas palavras".
- Na **1ª tentativa errada**, o aluno recebe só uma **dica** (uma pergunta que o faz pensar). A explicação completa aparece quando ele acerta ou a partir da 2ª tentativa. Assim o erro vira aprendizado, não um convite ao chute.
- Respostas em menos de 15 segundos ganham um aviso, e texto colado fica registrado.
- Tudo vai para `dados/registros.db` (SQLite): aluno, **ID da pergunta**, resposta, tempo, se colou, número da tentativa, nota e fontes. São exatamente os dados que faltaram no datathon.

## Como saberíamos que funcionou (para o slide final)

A aba **Números** e a rota `/metricas` mostram:
- nota média na 1ª tentativa (aprendizado real, sem tentativa e erro);
- ganho da 1ª para a 2ª tentativa (a dica ensinou?);
- % de respostas rápidas e de texto colado (esforço);
- perguntas com nota mais baixa (onde o professor deve reforçar).

Experimento proposto: metade das turmas usa o tutor e a outra metade usa os quizzes atuais. Comparar o ganho entre a prova diagnóstica e a prova real, e a correlação entre uso e ganho, que hoje é praticamente zero.

## Roteiro de demo ao vivo (2 minutos)

1. Mostrar a pergunta **70-01** (descontos sucessivos) e responder errado de propósito: "Sim, é 30% porque 10 + 20 = 30".
2. Mostrar o carimbo, a dica e as fontes com página.
3. Responder de novo, corretamente. A explicação completa aparece.
4. Ir à aba **Professor**, enviar um PDF de slides e mostrar que entrou.
5. Fechar na aba **Números**.

**Plano B:** gravem um vídeo curto da demo funcionando antes do pitch, caso a internet do local falhe.

## Problemas comuns

| Mensagem | O que fazer |
|---|---|
| `python não é reconhecido` | Reinstale o Python marcando "Add Python to PATH" (Windows) ou use `python3` (Mac). |
| `Falta a ANTHROPIC_API_KEY` | Confira se o arquivo se chama exatamente `.env` (não `.env.txt`) e se a chave está colada. |
| `Não consegui falar com o Claude: ... 401` | Chave errada ou sem créditos. |
| `Não encontrei texto no PDF` | O PDF é só imagem (escaneado). Use um PDF com texto selecionável ou exporte os slides de novo direto do PowerPoint/Google Slides. |
| Erro ao baixar o modelo na 1ª ingestão | Precisa de internet só nessa primeira vez. |
| `Address already in use` | Já tem um servidor aberto. Feche o outro terminal ou rode `uvicorn app:app --port 8001`. |
| Erro de embedding/dimensão após trocar `EMBEDDING` | Rode `python ingestao.py --zerar` e depois `python ingestao.py`. |
