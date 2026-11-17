"""
mobile_typesetter.py - Limpeza de Balões e Tipografia PT-BR Calibrada no Celular
Usa fontes profissionais embutidas (Anime Ace / Shout), métrica de acentos PT-BR
('ÁÇÃÊÓÚg'), entrelinha limpa e Pillow puro para máxima leveza no Android.
Regra de Ouro: Coeso, modular e estritamente < 300 linhas.
"""

import os
import zipfile
from PIL import Image, ImageDraw, ImageFont

import mobile_balloon_cleaner

FONTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "studio", "fonts")


def select_mobile_font(text, is_shout=False, is_thought=False):
    """Seleciona fonte consistente embutida no APK (evita troca em saudações simples)."""
    clean = (text or "").strip()
    real_shout = bool(
        is_shout
        or clean.endswith("!!")
        or clean.endswith("!?")
        or clean.endswith("?!")
        or clean.endswith("!?!")
    )
    if real_shout:
        for name in ("shout.ttf", "Komika_Axis.ttf", "animeace2_reg.ttf"):
            p = os.path.join(FONTS_DIR, name)
            if os.path.exists(p):
                return p

    if is_thought or (clean.startswith("(") and clean.endswith(")")):
        for name in ("dialogue_italic.ttf", "animeace2_reg.ttf", "dialogue.ttf"):
            p = os.path.join(FONTS_DIR, name)
            if os.path.exists(p):
                return p

    for name in ("animeace2_reg.ttf", "Komika_Axis.ttf", "dialogue.ttf"):
        p = os.path.join(FONTS_DIR, name)
        if os.path.exists(p):
            return p
    return None


def _load_font(font_path, size):
    if font_path and os.path.exists(font_path):
        try:
            return ImageFont.truetype(font_path, size)
        except Exception:
            pass
    for fallback in ("DejaVuSans-Bold.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(fallback, size)
        except Exception:
            continue
    return ImageFont.load_default()


def measure_ptbr_line_height(draw, font, line_spacing=1.22):
    """Mede altura real considerando acentos maiúsculos do PT-BR (ÁÇÃÊÓÚ)."""
    bb = draw.textbbox((0, 0), "ÁÇÃÊÓÚg", font=font)
    return max(10.0, float(bb[3] - bb[1])) * line_spacing


def clean_balloon_area(img_pil, xmin, ymin, xmax, ymax):
    """Limpa a cavidade fechada do balão (ou área segura) preservando o contorno preto."""
    cleaned_img, _ = mobile_balloon_cleaner.clean_and_locate_balloon(img_pil, xmin, ymin, xmax, ymax)
    return cleaned_img


def wrap_balanced_lines(text, font, max_width, draw):
    """Quebra o texto em linhas equilibradas sem hifenizar palavras curtas."""
    words = text.split()
    if not words:
        return []

    def _w(s):
        bb = draw.textbbox((0, 0), s, font=font)
        return bb[2] - bb[0]

    best_lines = None
    best_penalty = float("inf")
    total_chars = sum(len(w) for w in words) + max(0, len(words) - 1)

    for target_k in range(1, min(len(words), 7) + 1):
        lines = []
        idx = 0
        ok = True
        avg_c = total_chars / float(target_k)

        for li in range(target_k):
            if idx >= len(words):
                break
            curr = words[idx]
            idx += 1
            if _w(curr) > max_width:
                ok = False
                break
            while idx < len(words):
                rem_l = target_k - li - 1
                rem_w = len(words) - idx
                if rem_l > 0 and rem_w <= rem_l:
                    break
                cand = curr + " " + words[idx]
                if _w(cand) <= max_width:
                    if rem_l > 0 and len(curr) >= avg_c * 0.85 and len(cand) > avg_c * 1.22:
                        break
                    curr = cand
                    idx += 1
                else:
                    break
            lines.append(curr)

        if not ok or idx < len(words):
            continue

        widths = [_w(ln) for ln in lines]
        penalty = 0.0
        if len(lines) > 1:
            last_toks = lines[-1].split()
            if len(last_toks) == 1 and len(last_toks[0]) <= 3:
                penalty += 45.0
            mean_w = sum(widths) / float(len(widths))
            var_w = sum((w - mean_w) ** 2 for w in widths) / float(len(widths))
            penalty += ((var_w ** 0.5) / max(1.0, mean_w)) * 30.0

        if penalty < best_penalty:
            best_penalty = penalty
            best_lines = lines

    if best_lines:
        return best_lines

    # Fallback linear simples
    lines, cur = [], []
    for w in words:
        cand = " ".join(cur + [w])
        if _w(cand) <= max_width or not cur:
            cur.append(w)
        else:
            lines.append(" ".join(cur))
            cur = [w]
    if cur:
        lines.append(" ".join(cur))
    return lines


def render_dialogue_balloon(img_pil, text, xmin, ymin, xmax, ymax):
    """Renderiza fala em PT-BR com fonte consistente, acentos sem colisão e centralização."""
    clean = (text or "").strip().upper()
    if not clean:
        return img_pil

    draw = ImageDraw.Draw(img_pil)
    iw = img_pil.size[0]
    box_w = max(24, int(xmax - xmin))
    box_h = max(20, int(ymax - ymin))
    target_w = max(24, int(box_w * 0.92))
    target_h = max(20, int(box_h * 0.92))

    font_path = select_mobile_font(clean)
    base_fs = max(16, min(30, int(round(iw * 0.021))))
    max_fs = max(14, min(base_fs + 3, int(target_h * 0.44)))
    min_fs = max(12, int(round(iw * 0.0115)))

    best_font, best_lines, best_lh = None, [], 16.0
    for lead in (1.22, 1.15):
        for fs in range(max_fs, min_fs - 1, -1):
            font = _load_font(font_path, fs)
            lh = measure_ptbr_line_height(draw, font, lead)
            if int(target_h // lh) < 1:
                continue
            lines = wrap_balanced_lines(clean, font, target_w, draw)
            if lines and (len(lines) * lh) <= target_h + 2.0:
                best_font, best_lines, best_lh = font, lines, lh
                break
        if best_font:
            break

    if not best_font:
        best_font = _load_font(font_path, 11)
        best_lh = measure_ptbr_line_height(draw, best_font, 1.14)
        best_lines = wrap_balanced_lines(clean, best_font, target_w, draw)

    if not best_lines:
        return img_pil

    cx = (xmin + xmax) / 2.0
    cy = (ymin + ymax) / 2.0
    total_h = len(best_lines) * best_lh
    start_y = cy - (total_h / 2.0) + (best_lh / 2.0)

    for i, line in enumerate(best_lines):
        ly = start_y + i * best_lh
        draw.text((cx, ly), line, font=best_font, fill=(15, 15, 15), anchor="mm")

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
