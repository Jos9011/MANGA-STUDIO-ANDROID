"""
mobile_typesetter.py - Limpeza de Balões e Diagramação de Texto no Celular
Processa imagens usando OpenCV e Pillow diretamente na CPU do smartphone.
Regra de Ouro: Coeso, modular e estritamente < 300 linhas.
"""

import os
import zipfile
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


def clean_balloon_area(img_cv, xmin, ymin, xmax, ymax):
    """Limpa o texto original dentro da área do balão usando inpainting inteligente."""
    h_img, w_img = img_cv.shape[:2]
    xmin, ymin = max(0, int(xmin)), max(0, int(ymin))
    xmax, ymax = min(w_img, int(xmax)), min(h_img, int(ymax))
    if xmax <= xmin or ymax <= ymin:
        return img_cv

    roi = img_cv[ymin:ymax, xmin:xmax]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

    # Identifica texto escuro sobre fundo claro do balão
    _, mask = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY_INV)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask_dilated = cv2.dilate(mask, kernel, iterations=2)

    # Inpaint leve e rápido para processador ARM de celular
    cleaned_roi = cv2.inpaint(roi, mask_dilated, inpaintRadius=3, flags=cv2.INPAINT_TELEA)
    img_cv[ymin:ymax, xmin:xmax] = cleaned_roi
    return img_cv


def wrap_text_to_lines(text, font, max_width, draw):
    """Quebra o texto em linhas para caber dentro da largura do balão."""
    words = text.split()
    if not words:
        return []

    lines = []
    current_line = []
    for word in words:
        test_line = " ".join(current_line + [word])
        bbox = draw.textbbox((0, 0), test_line, font=font)
        w = bbox[2] - bbox[0]
        if w <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(" ".join(current_line))
                current_line = [word]
            else:
                lines.append(word)
                current_line = []
    if current_line:
        lines.append(" ".join(current_line))
    return lines


def render_dialogue_balloon(img_pil, text, xmin, ymin, xmax, ymax):
    """Renderiza a fala traduzida em português centralizada no balão."""
    draw = ImageDraw.Draw(img_pil)
    box_w = max(10, int(xmax - xmin))
    box_h = max(10, int(ymax - ymin))

    # Margem de respiro para o texto não encostar na borda do balão
    pad_w = int(box_w * 0.12)
    pad_h = int(box_h * 0.12)
    target_w = max(10, box_w - 2 * pad_w)
    target_h = max(10, box_h - 2 * pad_h)

    # Procura tamanho de fonte ideal dinamicamente
    font_size = max(12, int(box_h * 0.22))
    best_font = None
    best_lines = []

    while font_size >= 10:
        try:
            font = ImageFont.truetype("DejaVuSans-Bold.ttf", font_size)
        except Exception:
            font = ImageFont.load_default()

        lines = wrap_text_to_lines(text.upper(), font, target_w, draw)
        line_height = int(font_size * 1.25)
        total_h = len(lines) * line_height

        if total_h <= target_h or font_size <= 11:
            best_font = font
            best_lines = lines
            break
        font_size -= 2

    if not best_lines:
        return img_pil

    line_height = int(font_size * 1.25)
    total_h = len(best_lines) * line_height
    start_y = ymin + pad_h + max(0, (target_h - total_h) // 2)

    for i, line in enumerate(best_lines):
        bbox = draw.textbbox((0, 0), line, font=best_font)
        lw = bbox[2] - bbox[0]
        cur_x = xmin + (box_w - lw) // 2
        cur_y = start_y + i * line_height

        # Borda sutil branca (outline) para leitura nítida e texto em preto puro
        for ox in (-1, 1):
            for oy in (-1, 1):
                draw.text((cur_x + ox, cur_y + oy), line, font=best_font, fill=(255, 255, 255))
        draw.text((cur_x, cur_y), line, font=best_font, fill=(0, 0, 0))

    return img_pil


def make_cbz_package(folder_path, output_cbz):
    """Gera pacote .cbz pronto para Tachiyomi / Mihon."""
    exts = (".jpg", ".jpeg", ".png", ".webp")
    files = sorted([f for f in os.listdir(folder_path) if f.lower().endswith(exts)])
    with zipfile.ZipFile(output_cbz, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(os.path.join(folder_path, f), arcname=f)
    return output_cbz


def make_offline_reader(folder_path, title):
    """Cria leitor HTML embutido e responsivo para visualização offline no celular."""
    exts = (".jpg", ".jpeg", ".png", ".webp")
    files = sorted([f for f in os.listdir(folder_path) if f.lower().endswith(exts)])
    html_path = os.path.join(folder_path, "leitor.html")

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
<title>{title} — Leitor Mobile</title>
<style>
  body {{ margin:0; background:#111; color:#eee; font-family:sans-serif; text-align:center; }}
  .page {{ max-width:100%; display:block; margin:0 auto 8px auto; box-shadow:0 2px 10px rgba(0,0,0,0.8); }}
  .top-bar {{ position:sticky; top:0; background:rgba(18,18,18,0.9); padding:10px; font-weight:bold; backdrop-filter:blur(5px); }}
</style>
</head>
<body>
<div class="top-bar">📖 {title} ({len(files)} páginas)</div>
"""
    for fn in files:
        html += f'<img class="page" src="{fn}" loading="lazy" alt="{fn}" />\n'
    html += "</body></html>"

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    return html_path
