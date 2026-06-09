# Changelog

## 2026-06-09 — Atualizações rápidas

- Atualizado `README.md` para refletir a estrutura atual do projeto:
  - Substituído CLI legado `pdf_extractor_v2.py` por `python -m app.extractor` em exemplos.
  - Corrigidos caminhos de scripts para `scripts/setup.ps1` e `scripts/run.ps1`.
  - Adicionados exemplos `curl` detalhando o uso do endpoint `/html` com parâmetros (`paginas`, `metodo`, `tamanho_min_img`, `ocr_figuras`).
  - Melhorias gerais na seção de instalação e nos exemplos de uso.
- Adicionada flag `--tabelas-ocr` ao CLI e parâmetro `tabelas_ocr` ao endpoint `/tabelas` para tentar extração de tabelas via OCR.

> Observação: alterações de documentação apenas — código não modificado além do que já existia no repositório.
