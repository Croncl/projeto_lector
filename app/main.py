"""
Lector — API Web (app/main.py)
────────────────────────────────────────────────
Expõe todas as capacidades do Lector via HTTP.

Endpoints:
  POST /extract       → txt / json / blocos
  POST /html          → HTML dark-theme completo
  POST /diagnostico   → relatório do arquivo
  POST /headings      → lista de headings
  POST /figuras       → zip com imagens extraídas
  POST /tabelas       → JSON de tabelas (PDF only)
  GET  /health        → status da API
  GET  /docs          → Swagger UI (automático)

Uso:
  uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
"""

import io
import json
import zipfile
import tempfile
import base64
from pathlib import Path
from typing import Optional, Literal

from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, PlainTextResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

# ── Importa toda a lógica do extrator ─────────────────────────
from app import extractor as ext

# ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="Lector",
    description=(
        "**Lector** — leitor local de documentos.\n\n"
        "Extrai texto, figuras, tabelas e headings de arquivos **PDF** e "
        "**Jupyter Notebooks** (.ipynb). Gera saídas em TXT, JSON, blocos "
        "para LLMs (Claude, GPT) ou HTML dark-theme completo, sem depender de nenhuma nuvem."
    ),
    version="2.0.0",
    contact={"name": "Lector", "url": "https://github.com/"},
    license_info={"name": "MIT"},
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.get("/", tags=["UI"], response_class=HTMLResponse)
async def serve_ui():
    return FileResponse("app/static/index.html")


# ══════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════

def _detect_ipynb(filename: str) -> bool:
    return Path(filename).suffix.lower() == ".ipynb"

def _detect_image(filename: str) -> bool:
    return Path(filename).suffix.lower() in [".png", ".jpg", ".jpeg", ".webp"]


async def _save_upload(upload: UploadFile) -> Path:
    """Salva o upload em arquivo temporário e retorna o Path."""
    suffix = Path(upload.filename).suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await upload.read()
        tmp.write(content)
        return Path(tmp.name)


def _parse_paginas(paginas_str: Optional[str]) -> Optional[list]:
    if not paginas_str or paginas_str.strip().lower() == "string":
        return None
    try:
        return ext.parse_paginas(paginas_str)
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail=f"Parâmetro 'paginas' inválido: {e}. "
                   "Exemplos válidos: '1-10', '1,5,10', '1-5,8,12-20'.",
        )


# ══════════════════════════════════════════════════════════════
# GET /health
# ══════════════════════════════════════════════════════════════

@app.get("/health", tags=["Sistema"])
def health():
    """Verifica se a API Lector está funcionando."""
    return {"status": "ok", "projeto": "Lector", "version": "2.0.0"}


# ══════════════════════════════════════════════════════════════
# POST /diagnostico
# ══════════════════════════════════════════════════════════════

@app.post("/diagnostico", tags=["Análise"])
async def diagnostico(
    arquivo: UploadFile = File(..., description="Arquivo PDF ou .ipynb"),
):
    """
    Retorna um relatório completo sobre o arquivo enviado:
    número de páginas/células, presença de imagens, tabelas,
    método recomendado de extração e metadados.
    """
    tmp = await _save_upload(arquivo)
    try:
        is_ipynb = _detect_ipynb(arquivo.filename)
        is_image = _detect_image(arquivo.filename)
        if is_image:
            diag = ext.diagnosticar_imagem(str(tmp))
            diag["tipo"] = "imagem"
        elif is_ipynb:
            diag = ext.diagnosticar_ipynb(str(tmp))
            diag["tipo"] = "ipynb"
        else:
            diag = ext.diagnosticar(str(tmp))
            diag["tipo"] = "pdf"

        # Serializa metadados (podem conter objetos não-JSON)
        diag["metadados"] = {
            k: str(v) for k, v in diag.get("metadados", {}).items() if v
        }
        return JSONResponse(diag)
    finally:
        tmp.unlink(missing_ok=True)


# ══════════════════════════════════════════════════════════════
# POST /extract
# ══════════════════════════════════════════════════════════════

@app.post("/extract", tags=["Extração"])
async def extract(
    arquivo: UploadFile = File(..., description="Arquivo PDF, .ipynb ou Imagem"),
    modo: Literal["txt", "json", "blocos"] = Form("blocos"),
    paginas: Optional[str] = Form(None, description="Ex: '1-30' ou '1,5,10-20'"),
    metodo: Literal["auto", "texto", "visual", "ocr"] = Form("auto"),
    tokens: int = Form(3000, description="Tokens por bloco (modo blocos)"),
):
    """
    Extrai o conteúdo do arquivo.

    - **txt** → texto plano por página/célula
    - **json** → `{"1": "...", "2": "..."}` mapeando página → conteúdo
    - **blocos** → array de blocos prontos para enviar ao Claude, cada um
      com no máximo `tokens` tokens estimados
    """
    tmp = await _save_upload(arquivo)
    try:
        is_ipynb = _detect_ipynb(arquivo.filename)
        is_image = _detect_image(arquivo.filename)
        pags = _parse_paginas(paginas)

        if is_image:
            with open(str(tmp), "rb") as f:
                dados = f.read()
            b64 = base64.b64encode(dados).decode("utf-8")
            fmt = Path(arquivo.filename).suffix.lower().replace(".", "")
            mime = f"image/{fmt}"
            if fmt == "jpg": mime = "image/jpeg"
            
            # Retorna direto para imagens isoladas
            if modo == "blocos" or modo == "json":
                return JSONResponse({
                    "arquivo": arquivo.filename,
                    "tipo": "imagem",
                    "total_blocos": 1,
                    "tokens_por_bloco": tokens,
                    "blocos": [{
                        "bloco": 1,
                        "paginas": [1],
                        "conteudo": "Imagem fornecida isoladamente.",
                        "imagens": [{"mime": mime, "base64": b64}]
                    }]
                })
            else:
                # O usuário enviou uma imagem isolada mas quer .TXT. Fazer OCR.
                try:
                    from PIL import Image
                    import pytesseract
                    img = Image.open(str(tmp))
                    texto = pytesseract.image_to_string(img, lang="por+eng").strip()
                    if not texto:
                        texto = "[Nenhum texto legível encontrado na imagem]"
                except Exception as e:
                    texto = f"[Erro ao processar OCR da imagem: {e}]"
                return PlainTextResponse(f"=== IMAGEM: {arquivo.filename} ===\n\n{texto}")

        figs = []
        if is_ipynb:
            resultado, figs, _, _ = ext.extrair_dados_ipynb(str(tmp))
        else:
            diag = ext.diagnosticar(str(tmp))
            metodo_real = metodo if metodo != "auto" else diag["metodo_recomendado"]
            if metodo_real == "texto":
                resultado = ext.extrair_texto_pymupdf(str(tmp), pags)
            elif metodo_real == "ocr":
                resultado = ext.extrair_texto_ocr(str(tmp), paginas=pags)
            else:
                raise HTTPException(
                    status_code=422,
                    detail="Método 'visual' não é suportado via API. Use /html para visualização.",
                )
            if diag.get("tem_imagens"):
                figs = ext.extrair_figuras(str(tmp), paginas=pags)

        if modo == "txt":
            linhas = []
            for p, t in sorted(resultado.items()):
                if t:
                    linhas.append(f"\n{'='*60}\n  {'CÉLULA' if is_ipynb else 'PÁGINA'} {p}\n{'='*60}\n\n{t}")
            return PlainTextResponse("\n".join(linhas))

        elif modo == "json":
            payload = {str(p): t for p, t in sorted(resultado.items()) if t}
            return JSONResponse(payload)

        else:  # blocos
            figs_por_pag = {}
            for f in figs:
                figs_por_pag.setdefault(f["pagina"], []).append({
                    "mime": f.get("mime", "image/jpeg"),
                    "base64": f["base64"]
                })

            chars = tokens * 4
            blocos, atual, pags_bloco, imgs_bloco = [], "", [], []
            for pag, texto in sorted(resultado.items()):
                if not texto:
                    continue
                frag = f"\n[{'Célula' if is_ipynb else 'Página'} {pag}]\n{texto}\n"
                imgs_da_pag = figs_por_pag.get(pag, [])

                if len(atual) + len(frag) > chars and atual:
                    blocos.append({
                        "bloco": len(blocos) + 1,
                        "paginas": pags_bloco[:],
                        "conteudo": atual.strip(),
                        "imagens": imgs_bloco[:]
                    })
                    atual, pags_bloco, imgs_bloco = "", [], []
                
                atual += frag
                pags_bloco.append(pag)
                imgs_bloco.extend(imgs_da_pag)
                
            if atual or imgs_bloco:
                blocos.append({
                    "bloco": len(blocos) + 1,
                    "paginas": pags_bloco,
                    "conteudo": atual.strip(),
                    "imagens": imgs_bloco
                })
            return JSONResponse({
                "arquivo": arquivo.filename,
                "tipo": "ipynb" if is_ipynb else "pdf",
                "total_blocos": len(blocos),
                "tokens_por_bloco": tokens,
                "blocos": blocos,
            })
    finally:
        tmp.unlink(missing_ok=True)


# ══════════════════════════════════════════════════════════════
# POST /html
# ══════════════════════════════════════════════════════════════

@app.post("/html", tags=["Extração"], response_class=HTMLResponse)
async def gerar_html(
    arquivo: UploadFile = File(..., description="Arquivo PDF ou .ipynb"),
    paginas: Optional[str] = Form(None),
    metodo: Literal["auto", "texto", "ocr"] = Form("auto"),
    tamanho_min_img: int = Form(5),
    ocr_figuras: bool = Form(False),
):
    """
    Retorna um HTML dark-theme completo e auto-contido
    com figuras inline (base64), tabelas e sidebar navegável.
    """
    tmp = await _save_upload(arquivo)
    out = Path(tempfile.mktemp(suffix=".html"))
    try:
        is_ipynb = _detect_ipynb(arquivo.filename)
        pags = _parse_paginas(paginas)

        if is_ipynb:
            resultado, figs, heads, meta = ext.extrair_dados_ipynb(str(tmp))
            tabs = []
        else:
            diag = ext.diagnosticar(str(tmp))
            metodo_real = metodo if metodo != "auto" else diag["metodo_recomendado"]
            resultado = ext.extrair_texto_pymupdf(str(tmp), pags) if metodo_real == "texto" \
                else ext.extrair_texto_ocr(str(tmp), paginas=pags)

            figs = ext.extrair_figuras(str(tmp), paginas=pags,
                                       tamanho_minimo_kb=tamanho_min_img,
                                       descrever_com_ocr=ocr_figuras) if diag["tem_imagens"] else []
            tabs = ext.extrair_tabelas(str(tmp), paginas=pags) if diag["tem_tabelas"] else []
            heads = ext.extrair_headings(str(tmp))
            meta = ext.extrair_metadados(str(tmp))

        ext.gerar_html(resultado, figs, tabs, heads, meta, str(out), is_ipynb=is_ipynb)

        return HTMLResponse(out.read_text(encoding="utf-8"))
    finally:
        tmp.unlink(missing_ok=True)
        out.unlink(missing_ok=True)


# ══════════════════════════════════════════════════════════════
# POST /headings
# ══════════════════════════════════════════════════════════════

@app.post("/headings", tags=["Análise"])
async def headings(
    arquivo: UploadFile = File(..., description="Arquivo PDF ou .ipynb"),
):
    """Lista todos os headings/títulos detectados no arquivo."""
    tmp = await _save_upload(arquivo)
    try:
        is_ipynb = _detect_ipynb(arquivo.filename)
        if is_ipynb:
            _, _, heads, _ = ext.extrair_dados_ipynb(str(tmp))
        else:
            heads = ext.extrair_headings(str(tmp))
        return JSONResponse({"arquivo": arquivo.filename, "headings": heads})
    finally:
        tmp.unlink(missing_ok=True)


# ══════════════════════════════════════════════════════════════
# POST /figuras
# ══════════════════════════════════════════════════════════════

@app.post("/figuras", tags=["Extração"])
async def figuras(
    arquivo: UploadFile = File(..., description="Arquivo PDF ou .ipynb"),
    paginas: Optional[str] = Form(None),
    tamanho_min_img: int = Form(5),
    formato: Literal["zip", "json"] = Form("zip"),
):
    """
    Extrai figuras do arquivo.

    - **zip** → arquivo ZIP com todas as imagens
    - **json** → metadados + base64 de cada figura
    """
    tmp = await _save_upload(arquivo)
    try:
        is_ipynb = _detect_ipynb(arquivo.filename)
        pags = _parse_paginas(paginas)

        if is_ipynb:
            _, figs, _, _ = ext.extrair_dados_ipynb(str(tmp))
        else:
            figs = ext.extrair_figuras(str(tmp), paginas=pags,
                                       tamanho_minimo_kb=tamanho_min_img)

        if not figs:
            return JSONResponse({"mensagem": "Nenhuma figura encontrada.", "total": 0})

        if formato == "json":
            return JSONResponse({"total": len(figs), "figuras": [
                {k: v for k, v in f.items() if k != "base64"} for f in figs
            ]})

        # Retorna ZIP com as imagens
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for fig in figs:
                nome = f"pag{fig['pagina']:04d}_fig{fig['indice']:02d}.{fig['formato']}"
                zf.writestr(nome, base64.b64decode(fig["base64"]))
            meta_clean = [{k: v for k, v in f.items() if k != "base64"} for f in figs]
            zf.writestr("_metadados.json", json.dumps(meta_clean, ensure_ascii=False, indent=2))
        buf.seek(0)
        stem = Path(arquivo.filename).stem
        return StreamingResponse(
            buf,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{stem}_figuras.zip"'},
        )
    finally:
        tmp.unlink(missing_ok=True)


# ══════════════════════════════════════════════════════════════
# POST /tabelas
# ══════════════════════════════════════════════════════════════

@app.post("/tabelas", tags=["Extração"])
async def tabelas(
    arquivo: UploadFile = File(..., description="Arquivo PDF (ipynb não suportado)"),
    paginas: Optional[str] = Form(None),
):
    """Extrai tabelas do PDF (não disponível para notebooks)."""
    tmp = await _save_upload(arquivo)
    try:
        if _detect_ipynb(arquivo.filename):
            raise HTTPException(status_code=422, detail="Extração de tabelas não suportada para .ipynb")
        pags = _parse_paginas(paginas)
        tabs = ext.extrair_tabelas(str(tmp), paginas=pags)
        tabs_clean = [{k: v for k, v in t.items() if k != "html"} for t in tabs]
        return JSONResponse({"total": len(tabs_clean), "tabelas": tabs_clean})
    finally:
        tmp.unlink(missing_ok=True)
