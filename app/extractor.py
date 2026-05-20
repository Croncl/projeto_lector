"""
Lector — app/extractor.py  v2.0
───────────────────────────────────────────────────────────────
Motor de extração local para PDFs e Jupyter Notebooks (.ipynb).
Usado diretamente via CLI ou importado pela API FastAPI (app/main.py).

CAPACIDADES:
  ✅ Extração de texto (PyMuPDF / pdftotext)
  ✅ Extração de imagens/figuras embutidas no PDF (base64 → inline no HTML)
  ✅ Suporte a Jupyter Notebooks (.ipynb) — markdown, código e outputs
  ✅ Detecção de legendas próximas às figuras
  ✅ OCR em imagens com texto (pytesseract — opcional)
  ✅ Detecção de headings por tamanho de fonte
  ✅ Extração de metadados (título, autor, criador, datas)
  ✅ Extração de tabelas (pdfplumber)
  ✅ Detecção de estrutura (capítulos, seções, notas de rodapé)
  ✅ Geração de HTML dark-theme completo com figuras inline
  ✅ Geração de blocos JSON para envio gradual ao Claude / GPT
  ✅ Diagnóstico completo do arquivo

INSTALAÇÃO:
  pip install -r requirements.txt
  # Linux: sudo apt install poppler-utils tesseract-ocr tesseract-ocr-por
  # Mac:   brew install poppler tesseract

USO (CLI):
  python -m app.extractor livro.pdf
  python -m app.extractor livro.pdf --html
  python -m app.extractor notebook.ipynb --modo blocos --tokens 3000
  python -m app.extractor livro.pdf --diagnostico
"""

import sys
import os
import re
import json
import base64
import argparse
import subprocess
import tempfile
import io
from pathlib import Path
from io import BytesIO

# Configura encoding para UTF-8 no Windows (evita erro com emojis)
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# ══════════════════════════════════════════════════════════════
# 1. DIAGNÓSTICO
# ══════════════════════════════════════════════════════════════

def diagnosticar(pdf_path: str) -> dict:
    """Inspeciona o PDF e retorna relatório completo."""
    info = {
        "arquivo": pdf_path,
        "paginas": 0,
        "texto_extraivel": False,
        "fontes_ok": True,
        "parece_scan": False,
        "tem_imagens": False,
        "tem_tabelas": False,
        "metadados": {},
        "metodo_recomendado": "texto",
    }

    try:
        import fitz
        doc = fitz.open(pdf_path)
        info["paginas"] = len(doc)
        info["metadados"] = {k: v for k, v in doc.metadata.items() if v}

        amostras = []
        for i in range(min(3, len(doc))):
            texto = doc[i].get_text().strip()
            amostras.append(texto)
            if doc[i].get_images(full=True):
                info["tem_imagens"] = True

        texto_total = " ".join(amostras)
        chars_ok = sum(1 for c in texto_total if c.isprintable() and ord(c) > 31)
        total = max(len(texto_total), 1)

        if total < 50:
            info["parece_scan"] = True
            info["metodo_recomendado"] = "ocr"
        elif chars_ok / total < 0.5:
            info["fontes_ok"] = False
            info["metodo_recomendado"] = "visual"
        else:
            info["texto_extraivel"] = True
            info["metodo_recomendado"] = "texto"
            
        info["formato_recomendado"] = "blocos" if info["tem_imagens"] else "txt"

        doc.close()
    except ImportError:
        print("⚠️  PyMuPDF não instalado: pip install pymupdf")

    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages[:5]:
                if page.extract_tables():
                    info["tem_tabelas"] = True
                    break
    except ImportError:
        pass

    return info


# ══════════════════════════════════════════════════════════════
# 2. METADADOS
# ══════════════════════════════════════════════════════════════

def extrair_metadados(pdf_path: str) -> dict:
    """Retorna metadados completos do PDF."""
    try:
        import fitz
        doc = fitz.open(pdf_path)
        meta = dict(doc.metadata)
        meta["paginas_total"] = len(doc)
        doc.close()
        return meta
    except Exception as e:
        return {"erro": str(e)}


# ══════════════════════════════════════════════════════════════
# 3. EXTRAÇÃO DE TEXTO
# ══════════════════════════════════════════════════════════════

def extrair_texto_pymupdf(pdf_path: str, paginas: list = None) -> dict:
    """Extrai texto com PyMuPDF, página a página."""
    import fitz
    doc = fitz.open(pdf_path)
    resultado = {}
    indices = paginas if paginas else range(len(doc))
    for i in indices:
        if i >= len(doc):
            continue
        resultado[i + 1] = doc[i].get_text("text").strip()
    doc.close()
    return resultado


def extrair_texto_pdftotext(pdf_path: str, paginas: list = None) -> dict:
    """Usa pdftotext (poppler) — melhor para layouts complexos."""
    resultado = {}
    if paginas:
        for i in paginas:
            cmd = ["pdftotext", "-f", str(i+1), "-l", str(i+1), "-layout", pdf_path, "-"]
            try:
                out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
                resultado[i+1] = out.decode("utf-8", errors="replace").strip()
            except Exception as e:
                resultado[i+1] = f"[ERRO: {e}]"
    else:
        try:
            out = subprocess.check_output(
                ["pdftotext", "-layout", pdf_path, "-"], stderr=subprocess.DEVNULL)
            for idx, txt in enumerate(out.decode("utf-8", errors="replace").split("\f")):
                resultado[idx+1] = txt.strip()
        except FileNotFoundError:
            print("⚠️  pdftotext não encontrado. Instale o poppler.")
    return resultado


# ══════════════════════════════════════════════════════════════
# 4. EXTRAÇÃO DE FIGURAS / IMAGENS
# ══════════════════════════════════════════════════════════════

def extrair_figuras(pdf_path: str, paginas: list = None,
                    tamanho_minimo_kb: int = 5,
                    descrever_com_ocr: bool = False) -> list:
    """
    Extrai todas as imagens embutidas no PDF.

    Cada figura retornada contém:
      pagina, indice, largura, altura, formato, tamanho_kb,
      base64 (para embed inline no HTML), legenda_proxima, ocr_texto
    """
    try:
        import fitz
    except ImportError:
        print("⚠️  PyMuPDF necessário: pip install pymupdf")
        return []

    doc = fitz.open(pdf_path)
    figuras = []
    indices = paginas if paginas else range(len(doc))

    for i in indices:
        if i >= len(doc):
            continue
        page = doc[i]
        imgs = page.get_images(full=True)
        blocos_texto = page.get_text("blocks")

        for img_idx, img_info in enumerate(imgs):
            xref = img_info[0]
            try:
                base_image = doc.extract_image(xref)
            except Exception:
                continue

            dados = base_image["image"]
            fmt   = base_image["ext"]
            w, h  = base_image["width"], base_image["height"]
            kb    = len(dados) / 1024

            # Filtra imagens minúsculas (ícones, ornamentos)
            if kb < tamanho_minimo_kb or w < 50 or h < 50:
                continue

            mime = "image/png" if fmt == "png" else "image/jpeg"
            b64  = base64.b64encode(dados).decode("utf-8")

            legenda = _detectar_legenda(blocos_texto)
            ocr_txt = _ocr_em_imagem(dados, fmt) if descrever_com_ocr else ""

            figuras.append({
                "pagina": i + 1,
                "indice": img_idx + 1,
                "largura": w,
                "altura": h,
                "formato": fmt,
                "tamanho_kb": round(kb, 1),
                "mime": mime,
                "base64": b64,
                "legenda_proxima": legenda,
                "ocr_texto": ocr_txt,
            })
            print(f"   📷 pág {i+1} | fig {img_idx+1} | {w}×{h}px | {kb:.1f}KB")

    doc.close()
    print(f"\n   Total: {len(figuras)} figura(s) extraída(s)")
    return figuras


def _detectar_legenda(blocos_texto: list) -> str:
    """
    Heurística: detecta legendas pelo padrão textual
    (Figura X, Fig. X, Gráfico X, Fonte:, etc.)
    """
    padrao = re.compile(
        r'^(fig(ura)?\.?\s*\d|imagem\s*\d|gráfico\s*\d|tabela\s*\d|'
        r'quadro\s*\d|fonte[\s:]|source[\s:]|ilustração)',
        re.IGNORECASE
    )
    for bloco in blocos_texto:
        if len(bloco) >= 5:
            texto = str(bloco[4]).strip()
            if padrao.match(texto):
                return texto[:200]
    return ""


def _ocr_em_imagem(dados_img: bytes, fmt: str) -> str:
    """Aplica OCR na imagem para extrair texto interno (gráficos, diagramas)."""
    try:
        import pytesseract
        from PIL import Image
        img = Image.open(BytesIO(dados_img))
        return pytesseract.image_to_string(img, lang="por+eng").strip()
    except Exception:
        return ""


# ══════════════════════════════════════════════════════════════
# 5. EXTRAÇÃO DE TABELAS
# ══════════════════════════════════════════════════════════════

def extrair_tabelas(pdf_path: str, paginas: list = None) -> list:
    """
    Extrai tabelas com pdfplumber.
    Retorna lista com dados brutos e HTML pronto para embed.
    """
    try:
        import pdfplumber
    except ImportError:
        print("⚠️  pdfplumber necessário: pip install pdfplumber")
        return []

    tabelas = []
    with pdfplumber.open(pdf_path) as pdf:
        nums = paginas if paginas else range(len(pdf.pages))
        for i in nums:
            if i >= len(pdf.pages):
                continue
            for t_idx, tbl in enumerate(pdf.pages[i].extract_tables()):
                tbl = [l for l in tbl if any(c for c in l if c)]
                if len(tbl) < 2:
                    continue
                tabelas.append({
                    "pagina": i + 1,
                    "indice": t_idx + 1,
                    "linhas": len(tbl),
                    "colunas": max(len(l) for l in tbl),
                    "dados": tbl,
                    "html": _tabela_para_html(tbl),
                })
                print(f"   📊 pág {i+1} | {len(tbl)} × {len(tbl[0])}")
    return tabelas


def _tabela_para_html(dados: list) -> str:
    html = ['<table class="extracted-table">']
    for r, linha in enumerate(dados):
        tag = "th" if r == 0 else "td"
        html.append("<tr>")
        for c in linha:
            html.append(f"  <{tag}>{str(c or '').strip()}</{tag}>")
        html.append("</tr>")
    html.append("</table>")
    return "\n".join(html)


# ══════════════════════════════════════════════════════════════
# 6. HEADINGS
# ══════════════════════════════════════════════════════════════

def extrair_headings(pdf_path: str) -> list:
    """Detecta títulos por tamanho de fonte relativo ao corpo."""
    try:
        import fitz
    except ImportError:
        return []

    doc = fitz.open(pdf_path)
    todos_tam = []
    for page in doc:
        for b in page.get_text("dict")["blocks"]:
            if b.get("type") != 0:
                continue
            for l in b.get("lines", []):
                for s in l.get("spans", []):
                    if s.get("size", 0) > 0:
                        todos_tam.append(s["size"])

    medio = sorted(todos_tam)[len(todos_tam)//2] if todos_tam else 11
    headings = []

    for i, page in enumerate(doc):
        for b in page.get_text("dict")["blocks"]:
            if b.get("type") != 0:
                continue
            for l in b.get("lines", []):
                for s in l.get("spans", []):
                    tam = s.get("size", 0)
                    txt = s.get("text", "").strip()
                    negrito = "Bold" in s.get("font", "")
                    if txt and (tam > medio * 1.2 or (negrito and len(txt) < 100)):
                        razao = tam / max(medio, 1)
                        nivel = 1 if razao >= 1.8 else 2 if razao >= 1.4 else 3 if razao >= 1.2 else 4
                        headings.append({
                            "pagina": i + 1,
                            "texto": txt,
                            "tamanho": round(tam, 1),
                            "negrito": negrito,
                            "nivel": nivel,
                        })
    doc.close()
    return headings


# ══════════════════════════════════════════════════════════════
# 7. RASTERIZAÇÃO & OCR DE PÁGINAS
# ══════════════════════════════════════════════════════════════

def rasterizar_paginas(pdf_path: str, paginas: list = None,
                       dpi: int = 150, pasta_saida: str = None) -> list:
    if pasta_saida is None:
        pasta_saida = tempfile.mkdtemp(prefix="pdf_imgs_")
    os.makedirs(pasta_saida, exist_ok=True)
    prefixo = os.path.join(pasta_saida, "pag")

    if paginas:
        cmd = ["pdftoppm", "-jpeg", "-r", str(dpi),
               "-f", str(min(paginas)+1), "-l", str(max(paginas)+1), pdf_path, prefixo]
    else:
        cmd = ["pdftoppm", "-jpeg", "-r", str(dpi), pdf_path, prefixo]

    try:
        subprocess.run(cmd, check=True, stderr=subprocess.DEVNULL)
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        print(f"⚠️  Erro na rasterização: {e}")
        return []
    return sorted([str(p) for p in Path(pasta_saida).glob("pag-*.jpg")])


def extrair_texto_ocr(pdf_path: str, paginas: list = None, idioma: str = "por") -> dict:
    """OCR completo de páginas com pytesseract."""
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        print("⚠️  pip install pytesseract pillow")
        return {}

    imagens = rasterizar_paginas(pdf_path, paginas=paginas, dpi=200)
    resultado = {}
    for idx, img_path in enumerate(imagens):
        num = (min(paginas) if paginas else 0) + idx + 1
        try:
            texto = pytesseract.image_to_string(Image.open(img_path), lang=idioma)
            resultado[num] = texto.strip()
            print(f"  OCR pág {num} ✓")
        except Exception as e:
            resultado[num] = f"[ERRO: {e}]"
    return resultado


# ══════════════════════════════════════════════════════════════
# 8. GERAÇÃO DE HTML COMPLETO
# ══════════════════════════════════════════════════════════════

def gerar_html(texto_por_pagina: dict, figuras: list, tabelas: list,
               headings: list, metadados: dict, caminho_saida: str, is_ipynb: bool = False):
    """
    Gera HTML dark-theme completo com figuras inline (base64),
    tabelas estilizadas, sidebar navegável e todo o texto.
    Nenhuma dependência externa — arquivo único, funciona offline.
    """
    titulo = metadados.get("title") or Path(caminho_saida).stem
    autor  = metadados.get("author") or "Autor desconhecido"

    figs_pag  = {}
    for f in figuras:
        figs_pag.setdefault(f["pagina"], []).append(f)

    tabs_pag  = {}
    for t in tabelas:
        tabs_pag.setdefault(t["pagina"], []).append(t)

    # Sidebar navigation
    nav_items = ""
    for h in headings[:50]:
        slug   = re.sub(r'[^a-z0-9]', '-', h["texto"].lower())[:40]
        indent = (h["nivel"] - 1) * 14
        nav_items += (
            f'<a href="#{slug}" class="nav-h{h["nivel"]}" '
            f'style="padding-left:{indent+10}px">{h["texto"][:55]}</a>\n'
        )
    if not nav_items:
        nav_items = '<span class="nav-empty">Índice não disponível<br>(fontes com encoding customizado)</span>'

    # Conteúdo principal
    conteudo = ""
    for pag in sorted(texto_por_pagina.keys()):
        texto = texto_por_pagina[pag]
        
        conteudo += f'\n<div class="page-block">\n'
        lbl = "Célula" if is_ipynb else "Pág."
        conteudo += f'<span class="page-num">{lbl} {pag}</span>\n'

        if is_ipynb:
            blocos = texto.split("```")
            for i, b in enumerate(blocos):
                if i % 2 == 1:
                    linhas = b.split('\n', 1)
                    if len(linhas) > 1 and not linhas[0].isspace() and linhas[0].strip() in ["python", "bash", "json", "js"]:
                        codigo = linhas[1]
                    else:
                        codigo = b
                    codigo = codigo.replace("<", "&lt;").replace(">", "&gt;")
                    conteudo += f'<pre><code>{codigo}</code></pre>\n'
                else:
                    pars = [p.strip() for p in b.split("\n\n") if p.strip()]
                    for par in pars:
                        conteudo += f'<p>{par.replace(chr(10), "<br>")}</p>\n'
        else:
            pars  = [p.strip() for p in texto.split("\n\n") if p.strip()]
            for par in pars:
                linhas = par.split("\n")
                if len(linhas) == 1 and par.isupper() and 3 < len(par) < 80:
                    slug = re.sub(r'[^a-z0-9]', '-', par.lower())[:40]
                    conteudo += f'<h2 id="{slug}">{par}</h2>\n'
                elif len(linhas) == 1 and 5 < len(par) < 90 and not par.endswith("."):
                    slug = re.sub(r'[^a-z0-9]', '-', par.lower())[:40]
                    conteudo += f'<h3 id="{slug}">{par}</h3>\n'
                else:
                    conteudo += f'<p>{par.replace(chr(10), " ")}</p>\n'

        # Figuras desta página
        for fig in figs_pag.get(pag, []):
            leg  = fig.get("legenda_proxima") or f"Figura {fig['indice']} — Página {pag}"
            ocr  = fig.get("ocr_texto", "")
            ocr_html = f'<p class="fig-ocr">🔍 <em>Texto na imagem:</em> {ocr}</p>' if ocr else ""
            conteudo += f"""
<figure class="fig-block">
  <img src="data:{fig['mime']};base64,{fig['base64']}"
       alt="{leg}" loading="lazy" />
  <figcaption>
    <span class="fig-label">Fig. {fig['indice']}</span> {leg}
    {ocr_html}
    <span class="fig-meta">{fig['largura']}×{fig['altura']}px · {fig['tamanho_kb']}KB · {fig['formato'].upper()}</span>
  </figcaption>
</figure>
"""

        # Tabelas desta página
        for tab in tabs_pag.get(pag, []):
            conteudo += f"""
<div class="tab-block">
  <p class="tab-label">📊 Tabela {tab['indice']} — Página {pag}
    &nbsp;·&nbsp; {tab['linhas']} linhas × {tab['colunas']} colunas
  </p>
  <div class="tab-scroll">{tab['html']}</div>
</div>
"""
        conteudo += "</div>\n"

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>{titulo}</title>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{
  --bg:#1e1e2e;--bg2:#181825;--bg3:#11111b;
  --tx:#cdd6f4;--mt:#6c7086;
  --gn:#a6e3a1;--pk:#f38ba8;--yw:#f9e2af;
  --bl:#89b4fa;--mv:#cba6f7;--tl:#94e2d5;
  --br:#313244;
}}
html{{scroll-behavior:smooth}}
body{{background:var(--bg);color:var(--tx);font-family:'Georgia',serif;font-size:1.05rem;line-height:1.85}}
::-webkit-scrollbar{{width:6px}}
::-webkit-scrollbar-track{{background:var(--bg3)}}
::-webkit-scrollbar-thumb{{background:var(--br);border-radius:3px}}
.layout{{display:grid;grid-template-columns:250px 1fr;min-height:100vh}}
/* NAV */
nav{{position:sticky;top:0;height:100vh;overflow-y:auto;background:var(--bg2);
     border-right:1px solid var(--br);padding:1.4rem 1rem;display:flex;flex-direction:column;gap:.18rem}}
.brand{{font-size:.95rem;color:var(--gn);margin-bottom:1rem;padding-bottom:.8rem;
        border-bottom:1px solid var(--br);line-height:1.45}}
.brand small{{display:block;color:var(--mt);font-size:.72rem;margin-top:.25rem}}
nav a{{color:var(--mt);text-decoration:none;font-size:.8rem;padding:.32rem .55rem;
       border-radius:4px;border-left:2px solid transparent;
       transition:all .14s;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
nav a:hover{{color:var(--tx);background:#fff8;border-left-color:var(--pk)}}
.nav-h1{{color:var(--gn)!important;font-size:.85rem!important}}
.nav-h2{{color:var(--bl)!important}}
.nav-empty{{font-size:.78rem;color:var(--mt);padding:.5rem;line-height:1.6}}
/* MAIN */
main{{max-width:800px;margin:0 auto;padding:2.5rem 2.8rem 5rem}}
/* HEADER */
.doc-hdr{{background:linear-gradient(135deg,#1a1a2e,#0f3460);border:1px solid var(--br);
          border-radius:10px;padding:2rem;margin-bottom:2rem}}
.doc-hdr h1{{font-size:1.9rem;color:var(--gn);font-weight:normal;margin-bottom:.25rem}}
.doc-hdr .aut{{color:var(--mv);font-style:italic;margin-bottom:.8rem}}
.badges{{display:flex;flex-wrap:wrap;gap:.5rem;margin-top:.8rem}}
.badge{{background:#fff0d;border:1px solid var(--br);border-radius:16px;
        padding:.2rem .65rem;font-size:.75rem;color:var(--mt);font-family:monospace}}
.badge b{{color:var(--yw)}}
/* TEXTO */
h2{{font-family:'Palatino Linotype',serif;font-size:1.55rem;color:var(--gn);
    font-weight:normal;margin:2.5rem 0 .5rem;
    padding-bottom:.35rem;border-bottom:1px solid var(--br)}}
h3{{font-family:'Palatino Linotype',serif;font-size:1.1rem;color:var(--pk);
    font-weight:normal;margin:1.8rem 0 .45rem}}
p{{margin-bottom:.95rem}}
.page-block{{margin-bottom:1.2rem;position:relative}}
.page-num{{font-family:monospace;font-size:.68rem;color:var(--mt);
           border:1px solid var(--br);border-radius:10px;
           padding:.12rem .45rem;margin-bottom:.4rem;display:inline-block}}
/* FIGURAS */
.fig-block{{background:var(--bg2);border:1px solid var(--br);border-radius:10px;
            padding:1.2rem;margin:2rem 0;text-align:center}}
.fig-block img{{max-width:100%;height:auto;border-radius:6px;
                box-shadow:0 4px 24px #0006}}
figcaption{{margin-top:.75rem;font-size:.83rem;color:var(--mt);text-align:left}}
.fig-label{{background:var(--mv)20;border:1px solid var(--mv)50;color:var(--mv);
            border-radius:4px;padding:.08rem .38rem;font-size:.7rem;
            font-family:monospace;margin-right:.4rem}}
.fig-meta{{display:block;font-family:monospace;font-size:.68rem;
           color:var(--br);margin-top:.3rem}}
.fig-ocr{{font-size:.82rem;background:var(--bg3);border-radius:4px;
          padding:.45rem .65rem;margin-top:.4rem;color:var(--tx)}}
/* TABELAS */
.tab-block{{margin:2rem 0}}
.tab-label{{font-family:monospace;font-size:.74rem;color:var(--tl);margin-bottom:.5rem}}
.tab-scroll{{overflow-x:auto}}
.extracted-table{{width:100%;border-collapse:collapse;font-size:.86rem}}
.extracted-table th{{background:var(--br);color:var(--gn);padding:.55rem .75rem;
                     text-align:left;border-bottom:2px solid var(--gn)50}}
.extracted-table td{{padding:.45rem .75rem;border-bottom:1px solid var(--br);color:var(--tx)}}
.extracted-table tr:hover td{{background:#fff4}}
/* STATS */
.stats{{display:flex;flex-wrap:wrap;gap:.5rem;margin-bottom:1.8rem;
        padding:.9rem 1rem;background:var(--bg2);border:1px solid var(--br);border-radius:8px}}
@media(max-width:768px){{
  .layout{{grid-template-columns:1fr}}
  nav{{position:static;height:auto}}
  main{{padding:1.5rem 1rem}}
}}
::selection{{background:var(--mv);color:var(--bg3)}}
</style>
</head>
<body>
<div class="layout">
<nav>
  <div class="brand">{titulo}<small>{autor}</small></div>
  {nav_items}
</nav>
<main>
  <div class="doc-hdr">
    <h1>{titulo}</h1>
    <p class="aut">{autor}</p>
    <div class="badges">
      <span class="badge">Páginas: <b>{metadados.get('paginas_total','?')}</b></span>
      <span class="badge">Figuras: <b>{len(figuras)}</b></span>
      <span class="badge">Tabelas: <b>{len(tabelas)}</b></span>
      <span class="badge">Headings: <b>{len(headings)}</b></span>
    </div>
  </div>
  <div class="stats">
    <span class="badge">📄 {len(texto_por_pagina)} {'células' if is_ipynb else 'páginas'}</span>
    <span class="badge">🖼️ {len(figuras)} figura(s)</span>
    <span class="badge">📊 {len(tabelas)} tabela(s)</span>
    <span class="badge">📑 {len(headings)} título(s)</span>
  </div>
  {conteudo}
</main>
</div>
</body>
</html>"""

    with open(caminho_saida, "w", encoding="utf-8") as f:
        f.write(html)
    mb = os.path.getsize(caminho_saida) / (1024*1024)
    print(f"✅ HTML gerado: {caminho_saida} ({mb:.1f} MB)")


# ══════════════════════════════════════════════════════════════
# 9. SALVAR RESULTADOS
# ══════════════════════════════════════════════════════════════

def salvar_txt(resultado: dict, caminho: str):
    with open(caminho, "w", encoding="utf-8") as f:
        for p, t in sorted(resultado.items()):
            if t:
                f.write(f"\n{'='*60}\n  PÁGINA {p}\n{'='*60}\n\n{t}\n")
    print(f"✅ TXT: {caminho}")


def salvar_json(resultado: dict, caminho: str):
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump({str(p): t for p, t in sorted(resultado.items()) if t},
                  f, ensure_ascii=False, indent=2)
    print(f"✅ JSON: {caminho}")


def salvar_blocos_para_claude(resultado: dict, caminho: str, tokens: int = 3000):
    chars = tokens * 4
    blocos, atual, pags = [], "", []
    for pag, texto in sorted(resultado.items()):
        if not texto:
            continue
        frag = f"\n[Página {pag}]\n{texto}\n"
        if len(atual) + len(frag) > chars and atual:
            blocos.append({"bloco": len(blocos)+1, "paginas": pags[:], "conteudo": atual.strip()})
            atual, pags = "", []
        atual += frag
        pags.append(pag)
    if atual:
        blocos.append({"bloco": len(blocos)+1, "paginas": pags, "conteudo": atual.strip()})
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(blocos, f, ensure_ascii=False, indent=2)
    print(f"✅ {len(blocos)} blocos: {caminho}")


def salvar_figuras_disco(figuras: list, pasta: str):
    os.makedirs(pasta, exist_ok=True)
    for fig in figuras:
        nome = f"pag{fig['pagina']:04d}_fig{fig['indice']:02d}.{fig['formato']}"
        with open(os.path.join(pasta, nome), "wb") as f:
            f.write(base64.b64decode(fig["base64"]))
    # Salva metadados sem o base64
    meta = [{k: v for k, v in fig.items() if k != "base64"} for fig in figuras]
    with open(os.path.join(pasta, "_metadados.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"✅ {len(figuras)} figura(s) + metadados em: {pasta}/")


# ══════════════════════════════════════════════════════════════
# 10. UTILITÁRIOS & IPYNB
# ══════════════════════════════════════════════════════════════

def diagnosticar_ipynb(ipynb_path: str) -> dict:
    with open(ipynb_path, "r", encoding="utf-8") as f:
        nb = json.load(f)
    
    tem_imgs = any("image/png" in out.get("data", {}) 
                       for cell in nb.get("cells", []) 
                       for out in cell.get("outputs", []) 
                       if out.get("output_type") in ["display_data", "execute_result"])
                       
    return {
        "arquivo": ipynb_path,
        "paginas": len(nb.get("cells", [])),
        "texto_extraivel": True,
        "fontes_ok": True,
        "parece_scan": False,
        "tem_imagens": tem_imgs,
        "tem_tabelas": False,
        "metadados": nb.get("metadata", {}),
        "metodo_recomendado": "texto",
        "formato_recomendado": "blocos" if tem_imgs else "txt"
    }

def diagnosticar_imagem(img_path: str) -> dict:
    import os
    try:
        from PIL import Image
        import pytesseract
        img = Image.open(img_path)
        w, h = img.size
        # OCR rápido para detecção de texto
        texto_ocr = pytesseract.image_to_string(img, lang="por+eng").strip()
        tem_texto = len(texto_ocr) > 10
    except Exception:
        tem_texto = False
        w, h = 0, 0

    return {
        "arquivo": img_path,
        "paginas": 1,
        "texto_extraivel": False,
        "fontes_ok": True,
        "parece_scan": True,
        "tem_imagens": True,
        "tem_tabelas": False,
        "metadados": {
            "resolucao": f"{w}x{h}px",
            "tamanho_mb": f"{os.path.getsize(img_path) / (1024*1024):.2f} MB",
            "texto_legivel_detectado": "Sim" if tem_texto else "Não"
        },
        "metodo_recomendado": "ocr",
        "formato_recomendado": "blocos"
    }

def extrair_dados_ipynb(ipynb_path: str):
    with open(ipynb_path, 'r', encoding='utf-8') as f:
        nb = json.load(f)
        
    resultado = {}
    figuras = []
    headings = []
    
    cells = nb.get("cells", [])
    for idx, cell in enumerate(cells):
        cell_type = cell.get("cell_type")
        source = "".join(cell.get("source", []))
        texto_bloco = ""
        
        if cell_type == "markdown":
            texto_bloco += source
            for line in source.split("\n"):
                if line.lstrip().startswith("#"):
                    l_strip = line.lstrip()
                    nivel = len(l_strip) - len(l_strip.lstrip("#"))
                    texto = l_strip.lstrip("#").strip()
                    if texto:
                        headings.append({
                            "pagina": idx + 1,
                            "texto": texto,
                            "nivel": min(nivel, 4),
                            "tamanho": max(10, 24 - nivel * 2),
                            "negrito": True
                        })
        elif cell_type == "code":
            texto_bloco += f"```python\n{source}\n```"
            for out in cell.get("outputs", []):
                if out.get("output_type") == "stream":
                    text_out = "".join(out.get("text", []))
                    if len(text_out) > 1000:
                        text_out = text_out[:1000] + "\n... [TRUNCADO]"
                    texto_bloco += f"\n\n**Output:**\n```\n{text_out}\n```"
                elif out.get("output_type") in ["execute_result", "display_data"]:
                    data = out.get("data", {})
                    if "text/plain" in data:
                        text_out = "".join(data["text/plain"])
                        if len(text_out) > 1000:
                            text_out = text_out[:1000] + "\n... [TRUNCADO]"
                        texto_bloco += f"\n\n**Output:**\n```\n{text_out}\n```"
                    if "image/png" in data:
                        b64 = data["image/png"].replace("\n", "")
                        figuras.append({
                            "pagina": idx + 1,
                            "indice": len(figuras) + 1,
                            "largura": "Auto",
                            "altura": "Auto",
                            "formato": "png",
                            "tamanho_kb": round(len(b64) * 0.75 / 1024, 1),
                            "mime": "image/png",
                            "base64": b64,
                            "legenda_proxima": f"Output da célula {idx+1}",
                            "ocr_texto": ""
                        })
        if texto_bloco.strip():
            resultado[idx + 1] = texto_bloco.strip()
            
    metadados = nb.get("metadata", {})
    meta = {
        "title": metadados.get("title") or Path(ipynb_path).stem,
        "author": "Jupyter Notebook",
        "paginas_total": len(cells)
    }
    return resultado, figuras, headings, meta

def parse_paginas(texto: str) -> list:
    """
    Converte uma string de seleção de páginas em lista de índices base-0.

    Formatos aceitos: '1', '1,3,5', '1-10', '1-5,8,12-20'
    Lança ValueError se o formato for inválido.
    """
    indices = []
    for parte in texto.split(","):
        parte = parte.strip()
        if not parte:
            continue
        if "-" in parte:
            partes = parte.split("-", 1)
            a, b = partes[0].strip(), partes[1].strip()
            if not a.isdigit() or not b.isdigit():
                raise ValueError(
                    f"Intervalo inválido: '{parte}'. Use números, ex: '1-10'."
                )
            indices.extend(range(int(a) - 1, int(b)))
        else:
            if not parte.isdigit():
                raise ValueError(
                    f"Página inválida: '{parte}'. Use números, ex: '1,5,10' ou '1-20'."
                )
            indices.append(int(parte) - 1)
    return sorted(set(indices))


# ══════════════════════════════════════════════════════════════
# 11. MAIN
# ══════════════════════════════════════════════════════════════

def main():
    p = argparse.ArgumentParser(
        description="Extrai texto, figuras e tabelas de PDFs e IPYNB localmente.")
    p.add_argument("arquivo", help="Arquivo PDF ou Notebook (.ipynb)")
    p.add_argument("--output", "-o")
    p.add_argument("--modo", choices=["txt", "json", "blocos"], default="txt")
    p.add_argument("--paginas", "-p",
                   help="Ex: '1-30' ou '1,5,10-20'")
    p.add_argument("--metodo", choices=["auto", "texto", "visual", "ocr"], default="auto")
    p.add_argument("--dpi", type=int, default=150)
    p.add_argument("--tokens", type=int, default=3000)
    p.add_argument("--tamanho-min-img", type=int, default=5,
                   help="Tamanho mínimo de imagem em KB (padrão: 5)")
    p.add_argument("--html", action="store_true",
                   help="Gera HTML dark-theme com figuras e tabelas inline")
    p.add_argument("--figuras", action="store_true",
                   help="Extrai figuras como arquivos de imagem")
    p.add_argument("--tabelas", action="store_true",
                   help="Extrai tabelas como JSON")
    p.add_argument("--headings", action="store_true",
                   help="Lista headings detectados por tamanho de fonte")
    p.add_argument("--ocr-figuras", action="store_true",
                   help="Aplica OCR nas figuras extraídas (requer pytesseract)")
    p.add_argument("--diagnostico", action="store_true",
                   help="Apenas exibe diagnóstico, sem extrair")
    args = p.parse_args()

    if not os.path.exists(args.arquivo):
        print(f"❌ Arquivo não encontrado: {args.arquivo}")
        sys.exit(1)

    stem = Path(args.arquivo).stem
    ext = Path(args.arquivo).suffix.lower()
    is_ipynb = (ext == ".ipynb")

    print(f"\n📄 Analisando: {args.arquivo}")
    if is_ipynb:
        diag = diagnosticar_ipynb(args.arquivo)
        print(f"   Células:       {diag['paginas']}")
        print(f"   Tem imagens:   {'✅ Sim' if diag['tem_imagens'] else '—'}")
    else:
        diag = diagnosticar(args.arquivo)
        print(f"   Páginas:       {diag['paginas']}")
        print(f"   Texto OK:      {'✅' if diag['texto_extraivel'] else '❌ Não extraível'}")
        print(f"   Fontes OK:     {'✅' if diag['fontes_ok'] else '⚠️  Encoding corrompido'}")
        print(f"   Scan:          {'⚠️  Sim' if diag['parece_scan'] else '✅ Não'}")
        print(f"   Tem imagens:   {'✅ Sim' if diag['tem_imagens'] else '—'}")
        print(f"   Tem tabelas:   {'✅ Sim' if diag['tem_tabelas'] else '—'}")
        print(f"   Método sugeri: {diag['metodo_recomendado'].upper()}")
        
    if diag.get("metadados"):
        print(f"\n📋 Metadados:")
        for k, v in diag["metadados"].items():
            if v:
                print(f"   {k:20s}: {v}")

    if args.diagnostico:
        return

    paginas = parse_paginas(args.paginas) if args.paginas else None

    # Extrair todos os dados
    if is_ipynb:
        resultado, figs_extraidas, headings_extraidos, metadados_extraidos = extrair_dados_ipynb(args.arquivo)
        tabs_extraidas = []
    else:
        resultado = {}
        figs_extraidas = []
        tabs_extraidas = []
        headings_extraidos = []
        metadados_extraidos = extrair_metadados(args.arquivo)
        
        # ── Extração de texto PDF
        metodo = args.metodo if args.metodo != "auto" else diag["metodo_recomendado"]
        print(f"\n🔧 Método de extração: {metodo.upper()}")
        
        if metodo == "texto":
            resultado = extrair_texto_pymupdf(args.arquivo, paginas)
            amostra = " ".join(list(resultado.values())[:2])
            if sum(1 for c in amostra if c.isprintable()) < len(amostra) * 0.5:
                print("   ⚠️  Resultado parece corrompido — tente --metodo visual")
        elif metodo == "visual":
            pasta = f"{stem}_imagens"
            imgs = rasterizar_paginas(args.arquivo, paginas=paginas, dpi=args.dpi, pasta_saida=pasta)
            print(f"   ✅ {len(imgs)} imagens geradas em: {pasta}/")
            print("   📌 Envie as imagens ao Claude para leitura visual.")
            return
        elif metodo == "ocr":
            resultado = extrair_texto_ocr(args.arquivo, paginas=paginas)

    # ── Só headings
    if args.headings:
        print("\n🔍 Headings detectados:")
        heads = headings_extraidos if is_ipynb else extrair_headings(args.arquivo)
        for h in heads:
            indent = "  " * (h["nivel"]-1)
            lbl = "célula" if is_ipynb else "pág"
            print(f"  {lbl} {h['pagina']:4d} | h{h['nivel']} | {indent}{h['texto'][:70]}")
        return

    # ── Só figuras
    if args.figuras:
        print(f"\n🖼️  Extraindo figuras...")
        figs = figs_extraidas if is_ipynb else extrair_figuras(args.arquivo, paginas=paginas, tamanho_minimo_kb=args.tamanho_min_img, descrever_com_ocr=args.ocr_figuras)
        salvar_figuras_disco(figs, f"{stem}_figuras")
        return

    # ── Só tabelas
    if args.tabelas:
        if is_ipynb:
            print("\n⚠️ Tabelas não são suportadas em extração isolada de IPYNB.")
            return
        print(f"\n📊 Extraindo tabelas...")
        tabs = extrair_tabelas(args.arquivo, paginas=paginas)
        saida = args.output or f"{stem}_tabelas.json"
        tabs_json = [{k: v for k, v in t.items() if k != "html"} for t in tabs]
        with open(saida, "w", encoding="utf-8") as f:
            json.dump(tabs_json, f, ensure_ascii=False, indent=2)
        print(f"✅ {saida}")
        return

    # ── HTML completo
    if args.html:
        print("\n🎨 Gerando HTML...")
        if not is_ipynb:
            if diag["tem_imagens"]:
                print("   Extraindo figuras para embed inline...")
                figs_extraidas = extrair_figuras(args.arquivo, paginas=paginas, tamanho_minimo_kb=args.tamanho_min_img, descrever_com_ocr=args.ocr_figuras)
            if diag["tem_tabelas"]:
                print("   Extraindo tabelas...")
                tabs_extraidas = extrair_tabelas(args.arquivo, paginas=paginas)
            headings_extraidos = extrair_headings(args.arquivo)

        saida = args.output or f"{stem}.html"
        gerar_html(resultado, figs_extraidas, tabs_extraidas, headings_extraidos, metadados_extraidos, saida, is_ipynb=is_ipynb)
        return

    # ── Saída texto / json / blocos
    saida = args.output or f"{stem}.{'json' if args.modo == 'blocos' else args.modo}"
    print(f"\n💾 Salvando ({args.modo})...")
    if args.modo == "txt":
        salvar_txt(resultado, saida)
    elif args.modo == "json":
        salvar_json(resultado, saida)
    elif args.modo == "blocos":
        salvar_blocos_para_claude(resultado, saida, args.tokens)

    total_chars  = sum(len(t) for t in resultado.values())
    total_tokens = total_chars // 4
    print(f"\n📊 Resultado:")
    lbl = "Células processadas" if is_ipynb else "Páginas processadas"
    print(f"   {lbl} : {len(resultado)}")
    print(f"   Caracteres totais   : {total_chars:,}")
    print(f"   Tokens estimados    : ~{total_tokens:,}")
    if total_tokens > 50_000:
        print(f"   💡 Grande demais para uma mensagem — use --modo blocos --tokens 3000")


if __name__ == "__main__":
    main()