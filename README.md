# 📖 Lector

> *lector* (latim) — aquele que lê, o leitor.

Leitor local de documentos. Extrai e estrutura o conteúdo de arquivos **PDF** e **Jupyter Notebooks (`.ipynb`)** sem depender de nenhuma nuvem, gerando saídas prontas para consumo por LLMs (Claude, GPT, etc.) ou visualização em HTML dark-theme. Serve também como **API REST** via FastAPI.

---

## ✅ Capacidades

### PDF
| Recurso | Detalhe |
|---|---|
| Extração de texto | PyMuPDF (rápido) ou pdftotext (layout fiel) |
| Extração de figuras | Imagens embutidas salvas com base64 / disco |
| Detecção de legendas | Heurística por padrão textual (Fig., Tabela, Fonte:) |
| OCR em imagens | pytesseract — por, eng |
| Headings | Detecção por tamanho de fonte relativo ao corpo |
| Tabelas | pdfplumber — dados brutos + HTML estilizado |
| Metadados | Título, autor, criador, datas |
| HTML dark-theme | Sidebar navegável, figuras inline, tabelas, código |
| Blocos JSON | Chunking por tokens para envio gradual ao Claude, agora com imagens Base64 integradas. |
| Diagnóstico | Relatório completo do PDF, indicando o melhor método de extração e `formato_recomendado`. |

### Web / Multimodal
| Recurso | Detalhe |
|---|---|
| **Frontend Web** | Interface gráfica elegante (Dark Theme, Glassmorphism, Drag & Drop) acessível em `http://localhost:8000/` |
| **Multimodalidade** | O modo `blocos` embute as imagens detectadas diretamente em Base64 dentro do JSON. |
| **Imagens Avulsas** | Suporte para upload direto de imagens (`.jpg`, `.png`, `.webp`) para conversão pronta para IA. |

### Jupyter Notebook (`.ipynb`)
| Recurso | Detalhe |
|---|---|
| Células Markdown | Texto completo extraído |
| Células de Código | `source` limpo, sem `execution_count` ou IDs |
| Outputs de texto | `stream` e `text/plain` (truncados em 1000 chars) |
| Outputs de imagem | `image/png` embutido inline no HTML |
| Headings | Extraídos dos `#` do Markdown |
| HTML dark-theme | Blocos `<pre><code>` para código, figuras inline |
| Blocos JSON | Mesmo sistema de chunking do PDF |

---

## ⚙️ Instalação

### 1. Configurar ambiente (Windows — recomendado)

```powershell
.\setup.ps1
```

Isso cria um `venv` local e instala todas as dependências automaticamente.

### 2. Instalação manual

```bash
pip install pymupdf pdfplumber pillow pytesseract
```

#### Dependências opcionais (OCR e rasterização)

| Sistema | Comando |
|---|---|
| **Linux** | `sudo apt install poppler-utils tesseract-ocr tesseract-ocr-por` |
| **macOS** | `brew install poppler tesseract` |
| **Windows** | [Instalar Tesseract](https://github.com/UB-Mannheim/tesseract/wiki) + adicionar ao PATH |

> **OCR e `--metodo visual`** só são necessários para PDFs que são scans (imagens). Para PDFs com texto digital, as dependências do `pip` são suficientes.

---

## 🚀 Uso

### Sintaxe geral

```bash
python pdf_extractor_v2.py <arquivo> [opções]
```

`<arquivo>` pode ser um `.pdf`, um `.ipynb` ou uma Imagem (`.jpg`, `.png`, etc. se usando a Web/API).

No Windows com `venv`, use o wrapper:

```powershell
.\run.ps1 <arquivo> [opções]
```

---

## 📖 Exemplos de uso

### PDFs

#### Extração básica (texto → .txt)
```bash
python pdf_extractor_v2.py livro.pdf
```

#### Extração JSON estruturado
```bash
python pdf_extractor_v2.py livro.pdf --modo json
```

#### Blocos para envio gradual ao Claude
```bash
python pdf_extractor_v2.py livro.pdf --modo blocos --tokens 3000
```
> Gera um `.json` com array de blocos, cada um com no máximo ~3000 tokens (≈12 000 chars). Ideal para colar um bloco por vez no Claude.

#### Apenas as páginas 1 a 50
```bash
python pdf_extractor_v2.py livro.pdf --paginas 1-50 --modo blocos --tokens 4000
```

#### Páginas específicas não contíguas
```bash
python pdf_extractor_v2.py livro.pdf --paginas 1,5,10-20
```

#### Gerar HTML dark-theme completo (figuras + tabelas inline)
```bash
python pdf_extractor_v2.py livro.pdf --html
```

#### HTML com OCR nas figuras
```bash
python pdf_extractor_v2.py livro.pdf --html --ocr-figuras
```

#### Diagnóstico do PDF (sem extrair)
```bash
python pdf_extractor_v2.py livro.pdf --diagnostico
```

#### Listar headings detectados
```bash
python pdf_extractor_v2.py livro.pdf --headings
```

#### Extrair figuras para disco
```bash
python pdf_extractor_v2.py livro.pdf --figuras
```
> Salva as imagens em `<nome>_figuras/` + `_metadados.json`.

#### Extrair tabelas para JSON
```bash
python pdf_extractor_v2.py livro.pdf --tabelas
```

#### PDF que é scan (usar OCR de páginas inteiras)
```bash
python pdf_extractor_v2.py scan.pdf --metodo ocr
```

#### Definir arquivo de saída customizado
```bash
python pdf_extractor_v2.py livro.pdf --modo blocos -o minha_saida.json
```

---

### Jupyter Notebooks (`.ipynb`)

#### Extração básica (células → .txt)
```bash
python pdf_extractor_v2.py notebook.ipynb
```

#### Blocos para o Claude
```bash
python pdf_extractor_v2.py notebook.ipynb --modo blocos --tokens 2000
```

#### HTML dark-theme com código e gráficos inline
```bash
python pdf_extractor_v2.py notebook.ipynb --html
```

#### Diagnóstico do notebook
```bash
python pdf_extractor_v2.py notebook.ipynb --diagnostico
```

#### Listar headings das células Markdown
```bash
python pdf_extractor_v2.py notebook.ipynb --headings
```

#### Extrair figuras (outputs de imagem) para disco
```bash
python pdf_extractor_v2.py notebook.ipynb --figuras
```

---

## 🔧 Referência completa de opções

| Argumento | Tipo | Padrão | Descrição |
|---|---|---|---|
| `arquivo` | positional | — | Caminho para o `.pdf` ou `.ipynb` |
| `--output`, `-o` | string | auto | Caminho do arquivo de saída |
| `--modo` | `txt` \| `json` \| `blocos` | `txt` | Formato de saída de texto |
| `--paginas`, `-p` | string | todas | Páginas/células a processar. Ex: `1-30`, `1,5,10-20` |
| `--metodo` | `auto` \| `texto` \| `visual` \| `ocr` | `auto` | Método de extração de texto (PDF apenas) |
| `--tokens` | int | `3000` | Tamanho máximo de cada bloco (modo `blocos`) |
| `--dpi` | int | `150` | Resolução para rasterização (modo `visual`) |
| `--tamanho-min-img` | int | `5` | Tamanho mínimo de imagem a extrair, em KB |
| `--html` | flag | — | Gera HTML dark-theme completo |
| `--figuras` | flag | — | Extrai figuras para disco (sem extrair texto) |
| `--tabelas` | flag | — | Extrai tabelas para JSON (PDF apenas) |
| `--headings` | flag | — | Lista títulos detectados (sem extrair texto) |
| `--ocr-figuras` | flag | — | Aplica OCR nas figuras extraídas |
| `--diagnostico` | flag | — | Exibe relatório e encerra (sem extrair) |

---

## 📂 Arquivos de saída

| Operação | Arquivo gerado |
|---|---|
| `--modo txt` | `<nome>.txt` |
| `--modo json` | `<nome>.json` |
| `--modo blocos` | `<nome>.json` (array de blocos) |
| `--html` | `<nome>.html` |
| `--figuras` | `<nome>_figuras/` (imagens + `_metadados.json`) |
| `--tabelas` | `<nome>_tabelas.json` |
| `--metodo visual` | `<nome>_imagens/` (JPEGs das páginas) |

---

## 🧩 Métodos de extração de texto (PDF)

| Método | Quando usar |
|---|---|
| `auto` *(padrão)* | O script decide com base no diagnóstico |
| `texto` | PDFs digitais normais (mais rápido e preciso) |
| `visual` | PDFs com encoding corrompido — gera imagens para análise manual ou envio visual ao Claude |
| `ocr` | PDFs que são scans de papel — pytesseract lê as páginas rasterizadas |

---

## 💡 Fluxo recomendado para estudo com Claude

```bash
# 1. Diagnosticar o arquivo
python pdf_extractor_v2.py livro.pdf --diagnostico

# 2. Gerar blocos de ~3000 tokens
python pdf_extractor_v2.py livro.pdf --modo blocos --tokens 3000 -o blocos.json

# 3. No Claude: colar um bloco por vez e pedir resumo/análise
```

Para notebooks:
```bash
python pdf_extractor_v2.py HandsOn-Q-Learning.ipynb --modo blocos --tokens 2000 -o blocos_nb.json
```

---

## 🗂️ Estrutura do projeto

```
.
├── app/                      # Pacote Python principal
│   ├── __init__.py
│   ├── extractor.py          # Lógica de extração (PDF + .ipynb)
│   └── main.py               # FastAPI — API Web
│
├── materiais/                # PDFs, notebooks e arquivos de estudo
│   ├── *.pdf
│   ├── *.ipynb
│   └── *.txt
│
├── scripts/                  # Utilitários Windows
│   ├── setup.ps1             # Cria venv e instala dependências
│   └── run.ps1               # Inicia a API (suporta -Reload e -Port)
│
├── venv/                     # Ambiente virtual Python (não versionado)
├── Dockerfile                # Container multi-stage: Tesseract + Poppler
├── docker-compose.yml        # Orquestração do container
├── requirements.txt          # Dependências Python
├── .gitignore
└── README.md
```

---

## 🐳 Docker — API Web (FastAPI)

O script pode ser servido como API HTTP via Docker, expondo todos os endpoints
com documentação interativa automática (Swagger).

### Subir a API

```bash
# Build + start (primeira vez)
docker compose up --build

# Execuções seguintes
docker compose up
```

A API ficará disponível em `http://localhost:8000`.

### Endpoints disponíveis

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/` | **Interface Web (Frontend)** interativa |
| `GET` | `/health` | Status da API |
| `GET` | `/docs` | Swagger UI interativo |
| `POST` | `/diagnostico` | Relatório do arquivo (inclui `formato_recomendado`) |
| `POST` | `/extract` | Extração de texto (txt / json / blocos) |
| `POST` | `/html` | HTML dark-theme completo |
| `POST` | `/headings` | Lista de headings |
| `POST` | `/figuras` | Figuras em ZIP ou JSON |
| `POST` | `/tabelas` | Tabelas em JSON (PDF only) |

### Exemplos com `curl`

#### Diagnóstico
```bash
curl -F "arquivo=@livro.pdf" http://localhost:8000/diagnostico
```

#### Blocos para o Claude
```bash
curl -F "arquivo=@livro.pdf" \
     -F "modo=blocos" \
     -F "tokens=3000" \
     http://localhost:8000/extract
```

#### Apenas páginas 1-20
```bash
curl -F "arquivo=@livro.pdf" \
     -F "modo=blocos" \
     -F "paginas=1-20" \
     -F "tokens=4000" \
     http://localhost:8000/extract
```

#### HTML dark-theme salvo em arquivo
```bash
curl -F "arquivo=@livro.pdf" \
     http://localhost:8000/html \
     -o livro.html
```

#### Notebook
```bash
curl -F "arquivo=@notebook.ipynb" \
     -F "modo=blocos" \
     -F "tokens=2000" \
     http://localhost:8000/extract
```

#### Baixar figuras como ZIP
```bash
curl -F "arquivo=@livro.pdf" \
     -F "formato=zip" \
     http://localhost:8000/figuras \
     -o figuras.zip
```

### Python (requests)

```python
import requests

# Blocos para o Claude
with open("livro.pdf", "rb") as f:
    r = requests.post(
        "http://localhost:8000/extract",
        files={"arquivo": f},
        data={"modo": "blocos", "tokens": 3000},
    )
blocos = r.json()["blocos"]

# Iterar e enviar ao Claude um a um
for bloco in blocos:
    print(f"Bloco {bloco['bloco']} — {len(bloco['conteudo'])} chars")
```

### Sem Docker (desenvolvimento local)

```bash
# Instalar dependências
pip install -r requirements.txt

# Rodar API com hot-reload
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
---

## ❓ Problemas comuns

**`❌ Arquivo não encontrado`**
> Verifique o caminho. Use aspas se houver espaços: `"Meu Livro.pdf"`.

**Texto extraído com caracteres estranhos / corrompido**
> Use `--metodo visual` (gera imagens) ou `--metodo ocr` para PDFs escaneados.

**`⚠️ pdftotext não encontrado`**
> Instale o Poppler (veja seção Instalação). O método padrão `texto` usa PyMuPDF e não precisa do Poppler.

**Figuras não extraídas**
> Ajuste `--tamanho-min-img 1` para capturar imagens menores que o padrão de 5KB.

**Notebook sem outputs**
> Se as células nunca foram executadas, não há outputs para extrair. Execute o notebook no Jupyter primeiro.
