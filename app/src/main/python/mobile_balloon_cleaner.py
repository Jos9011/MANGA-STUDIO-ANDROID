"""
mobile_balloon_cleaner.py - Limpeza Completa de Cavidade de Balão (100% Pillow Puro)
Detecta o interior fechado de balões brancos sem OpenCV, apaga resíduos soltos
('I', letras coloridas/cinzas) preservando o contorno preto e centraliza o texto.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

from collections import deque
from PIL import Image, ImageDraw, ImageFilter


def _is_bright_paper(r, g, b):
    """Identifica pixels de papel claro/branco (baixa saturação, alta luminância)."""
    mx = max(r, g, b)
    mn = min(r, g, b)
    return mx >= 212 and mn >= 188 and (mx - mn) <= 42


def _flood_fill_mask(grid, w, h, seeds):
    """BFS 4-conectado em grade binária 1D (rápido e leve em memória no Android)."""
    visited = bytearray(w * h)
    q = deque()
    for sx, sy in seeds:
        idx = sy * w + sx
        if grid[idx] and not visited[idx]:
            visited[idx] = 1
            q.append((sx, sy))

    while q:
        x, y = q.popleft()
        if x > 0:
            ni = y * w + (x - 1)
            if grid[ni] and not visited[ni]:
                visited[ni] = 1
                q.append((x - 1, y))
        if x + 1 < w:
            ni = y * w + (x + 1)
            if grid[ni] and not visited[ni]:
                visited[ni] = 1
                q.append((x + 1, y))
        if y > 0:
            ni = (y - 1) * w + x
            if grid[ni] and not visited[ni]:
                visited[ni] = 1
                q.append((x, y - 1))
        if y + 1 < h:
            ni = (y + 1) * w + x
            if grid[ni] and not visited[ni]:
                visited[ni] = 1
                q.append((x, y + 1))
    return visited


def _fill_interior_holes(comp, w, h):
    """Preenche todos os furos internos cercados pelo balão (letras escuras e coloridas)."""
    inv = bytearray(1 - b for b in comp)
    border_seeds = []
    for x in range(w):
        if inv[x]:
            border_seeds.append((x, 0))
        if inv[(h - 1) * w + x]:
            border_seeds.append((x, h - 1))
    for y in range(1, h - 1):
        if inv[y * w]:
            border_seeds.append((0, y))
        if inv[y * w + (w - 1)]:
            border_seeds.append((w - 1, y))

    outside = _flood_fill_mask(inv, w, h, border_seeds)
    # Tudo que não é exterior pertence ao interior fechado do balão (papel + letras internas)
    return bytearray(0 if o else 1 for o in outside)


def clean_and_locate_balloon(img_pil, xmin, ymin, xmax, ymax):
    """
    Detecta e limpa a cavidade completa de um balão branco ao redor da caixa fornecida.
    Retorna (img_pil, safe_box) onde safe_box = (sx0, sy0, sx1, sy1) para diagramação.
    """
    iw, ih = img_pil.size
    xmin = max(0, min(iw - 1, int(xmin)))
    ymin = max(0, min(ih - 1, int(ymin)))
    xmax = max(xmin + 1, min(iw, int(xmax)))
    ymax = max(ymin + 1, min(ih, int(ymax)))
    bw, bh = xmax - xmin, ymax - ymin

    # Janela local proporcional ao balão (rápida no smartphone)
    pad_x = min(130, max(45, int(bw * 0.55)))
    pad_y = min(110, max(40, int(bh * 0.55)))
    wx0, wy0 = max(0, xmin - pad_x), max(0, ymin - pad_y)
    wx1, wy1 = min(iw, xmax + pad_x), min(ih, ymax + pad_y)
    ww, wh = wx1 - wx0, wy1 - wy0

    crop = img_pil.crop((wx0, wy0, wx1, wy1)).convert("RGB")
    px_data = list(crop.getdata())
    bright_grid = bytearray(1 if _is_bright_paper(r, g, b) else 0 for (r, g, b) in px_data)

    # Sementes brilhantes dentro da caixa detectada
    ox0, oy0 = max(0, xmin - wx0), max(0, ymin - wy0)
    ox1, oy1 = min(ww, xmax - wx0), min(wh, ymax - wy0)
    seeds = []
    for y in range(oy0, oy1, 2):
        row_off = y * ww
        for x in range(ox0, ox1, 2):
            if bright_grid[row_off + x]:
                seeds.append((x, y))

    if len(seeds) < 8:
        # Fundo escuro ou arte direta: limpeza cirúrgica suave apenas dentro da caixa
        draw = ImageDraw.Draw(img_pil)
        draw.rectangle([xmin, ymin, xmax, ymax], fill=(255, 255, 255))
        return img_pil, (xmin, ymin, xmax, ymax)

    comp = _flood_fill_mask(bright_grid, ww, wh, seeds)
    filled = _fill_interior_holes(comp, ww, wh)

    # Verificação anti-vazamento (evita pintar fundo aberto sem contorno fechado)
    top_t = sum(filled[x] for x in range(ww)) / float(max(1, ww))
    bot_t = sum(filled[(wh - 1) * ww + x] for x in range(ww)) / float(max(1, ww))
    lft_t = sum(filled[y * ww] for y in range(wh)) / float(max(1, wh))
    rgt_t = sum(filled[y * ww + (ww - 1)] for y in range(wh)) / float(max(1, wh))
    open_sides = sum(1 for t in (top_t, bot_t, lft_t, rgt_t) if t > 0.42)
    fill_ratio = sum(filled) / float(max(1, ww * wh))

    if open_sides >= 3 or (open_sides >= 2 and fill_ratio > 0.65):
        draw = ImageDraw.Draw(img_pil)
        draw.rectangle([xmin, ymin, xmax, ymax], fill=(255, 255, 255))
        return img_pil, (xmin, ymin, xmax, ymax)

    # Amostra a cor real do papel do balão
    rs, gs, bs = [], [], []
    for idx in range(0, len(comp), 4):
        if comp[idx]:
            r, g, b = px_data[idx]
            rs.append(r)
            gs.append(g)
            bs.append(b)
    if rs:
        rs.sort()
        gs.sort()
        bs.sort()
        mid = len(rs) // 2
        fill_rgb = (rs[mid], gs[mid], bs[mid])
        if min(fill_rgb) >= 244 and (max(fill_rgb) - min(fill_rgb)) <= 10:
            fill_rgb = (255, 255, 255)
    else:
        fill_rgb = (255, 255, 255)

    # Erosão segura de 2px via Pillow MinFilter(5) para jamais encostar no contorno preto
    mask_img = Image.frombytes("L", (ww, wh), bytes(255 if v else 0 for v in filled))
    safe_mask = mask_img.filter(ImageFilter.MinFilter(5))
    safe_bytes = safe_mask.tobytes()

    # Varre 100% da cavidade segura (apaga letras originais, 'I', cores residuais e halos)
    new_px = list(px_data)
    min_x, min_y, max_x, max_y = ww, wh, 0, 0
    for idx, m_val in enumerate(safe_bytes):
        if m_val:
            new_px[idx] = fill_rgb
            y, x = divmod(idx, ww)
            if x < min_x:
                min_x = x
            if x > max_x:
                max_x = x
            if y < min_y:
                min_y = y
            if y > max_y:
                max_y = y

    crop.putdata(new_px)
    img_pil.paste(crop, (wx0, wy0))

    if max_x > min_x + 20 and max_y > min_y + 16:
        in_x = max(8, int((max_x - min_x) * 0.08))
        in_y = max(6, int((max_y - min_y) * 0.10))
        safe_box = (
            wx0 + min_x + in_x,
            wy0 + min_y + in_y,
            wx0 + max_x - in_x,
            wy0 + max_y - in_y,
        )
    else:
        safe_box = (xmin, ymin, xmax, ymax)

    return img_pil, safe_box
