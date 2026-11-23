"""
mobile_translator.py - Motor de Tradução para Smartphone (APIs Cloud)
Orquestra página a página: IA Vision -> limpeza de balão -> diagramação PT-BR.
Falhas por página são registradas e reportadas (nunca escondidas como "sucesso").
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import base64
import io
import os
from PIL import Image

import mobile_balloon_cleaner
import mobile_config
import mobile_drive_helper
import mobile_image_io
import mobile_typesetter
from mobile_vision_api import PROMPT, call_vision_api, extract_json_bubbles, collect_keys  # noqa: F401

IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".avif", ".bmp")


def encode_image_base64(img, max_dim=1400):
    """
    Redimensiona e codifica a página em base64 (aceita caminho ou PIL.Image já aberta).
    Retorna (b64, (altura_enviada, largura_enviada)).
    """
    im = img if isinstance(img, Image.Image) else mobile_image_io.open_rgb(img)
    w, h = im.size
    if max(w, h) > max_dim:
        scale = max_dim / float(max(w, h))
        im = im.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=85)
    sent_w, sent_h = im.size
    return base64.b64encode(buf.getvalue()).decode("utf-8"), (sent_h, sent_w)


def box_to_pixels(box, sent_w, sent_h, real_w, real_h):
    """
    Converte box_2d [ymin, xmin, ymax, xmax] para pixels da imagem original.
    Aceita escala 0-1000 (padrão Gemini), 0-1 (fração) ou pixels da imagem enviada (>1000).
    Retorna (xmin, ymin, xmax, ymax) ou None se a caixa for inválida.
    """
    try:
        vals = [float(v) for v in box]
    except (TypeError, ValueError):
        return None
    if len(vals) != 4 or min(vals) < 0:
        return None
    y0, x0, y1, x1 = vals
    peak = max(vals)
    if peak <= 1.0:
        sx, sy = real_w, real_h
    elif peak > 1000.0:
        sx, sy = real_w / float(max(1, sent_w)), real_h / float(max(1, sent_h))
    else:
        sx, sy = real_w / 1000.0, real_h / 1000.0
    y0, y1 = sorted((y0 * sy, y1 * sy))
    x0, x1 = sorted((x0 * sx, x1 * sx))
    x0, x1 = max(0, int(x0)), min(real_w, int(x1))
    y0, y1 = max(0, int(y0)), min(real_h, int(y1))
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    return x0, y0, x1, y1


def process_single_page(img_path, out_path, config):
    """Processa página: chama Vision, varre cavidades de balão e diagrama em PT-BR. Retorna nº de balões."""
    img_pil = mobile_image_io.open_rgb(img_path)  # Pillow ou decodificador nativo do Android
    b64, (sent_h, sent_w) = encode_image_base64(img_pil, config.get("max_image_dim", 1400))
    bubbles = call_vision_api(b64, config)

    real_w, real_h = img_pil.size
    safe_regions = []

    for item in bubbles:
        if not isinstance(item, dict):
            continue
        trans = str(item.get("translation") or "").strip()
        px = box_to_pixels(item.get("box_2d") or [], sent_w, sent_h, real_w, real_h)
        if not px:
            continue
        xmin, ymin, xmax, ymax = px
        img_pil, sbox = mobile_balloon_cleaner.clean_and_locate_balloon(img_pil, xmin, ymin, xmax, ymax)
        if trans:
            safe_regions.append((sbox, trans))

    for (sx0, sy0, sx1, sy1), trans in safe_regions:
        img_pil = mobile_typesetter.render_dialogue_balloon(img_pil, trans, sx0, sy0, sx1, sy1)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img_pil.save(out_path, "JPEG", quality=92)
    return len(safe_regions)


def list_page_images(folder):
    """
    Lista páginas em ordem natural (1, 2, 10), incluindo subpastas de capítulos.
    Retorna [(caminho_entrada, nome_saida.jpg)], com nome de saída único por subpasta.
    """
    pages = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if not d.startswith(".") and "[PT-BR]" not in d]
        for f in files:
            if f.lower().endswith(IMG_EXTS) and not f.startswith("."):
                rel = os.path.relpath(os.path.join(root, f), folder)
                pages.append(rel)
    pages.sort(key=lambda r: [mobile_drive_helper.natural_sort_key(p) for p in r.replace("\\", "/").split("/")])
    out = []
    for rel in pages:
        stem = os.path.splitext(rel.replace("\\", "/"))[0].replace("/", "_")
        out.append((os.path.join(folder, rel), f"{stem}.jpg"))
    return out


def translate_manga_folder(input_folder, output_folder=None, progress_cb=None):
    """
    Traduz páginas com suporte a pausa/parada e preservação de progresso parcial.
    Retorna dict: output, cbz, total, translated, failed, errors.
    """
    cfg = mobile_config.load_config()
    pages = list_page_images(input_folder)
    if not pages:
        raise ValueError(f"Nenhuma imagem encontrada em: {input_folder}")

    if not any(collect_keys(cfg, p) for p in ("groq", "gemini", "openrouter")):
        raise ValueError("Nenhuma chave de API configurada! Adicione uma chave em Configurações.")

    if not output_folder:
        base_name = os.path.basename(input_folder.rstrip("/\\"))
        output_folder = os.path.join(cfg.get("output_dir", "/sdcard/MANGAS [PT-BR]"), f"{base_name} [PT-BR]")

    os.makedirs(output_folder, exist_ok=True)
    total = len(pages)
    translated, errors, fallback_copies = 0, [], []

    def notify(cur, msg):
        if progress_cb:
            progress_cb("translating", cur, total, msg)

    try:
        for idx, (in_p, out_name) in enumerate(pages):
            out_p = os.path.join(output_folder, out_name)
            notify(idx + 1, f"Traduzindo página {idx + 1}/{total} ({out_name})...")
            try:
                n = process_single_page(in_p, out_p, cfg)
                translated += 1
                if n == 0:
                    notify(idx + 1, f"ℹ️ Página {idx + 1}: nenhum balão de fala detectado.")
            except Exception as e:
                err = str(e)
                errors.append({"page": out_name, "error": err})
                notify(idx + 1, f"⚠️ Página {idx + 1} NÃO traduzida ({out_name}): {err[:220]}")
                if not os.path.exists(out_p):
                    try:
                        mobile_image_io.open_rgb(in_p).save(out_p, "JPEG", quality=90)
                        fallback_copies.append(out_p)
                    except Exception as save_err:
                        print(f"[!] Erro no fallback de cópia {out_name}: {save_err}")
    finally:
        if any(f.lower().endswith(IMG_EXTS) for f in os.listdir(output_folder)):
            mobile_typesetter.make_offline_reader(output_folder, os.path.basename(output_folder))

    if translated == 0:
        # Nada foi traduzido: não deixa uma obra "falsa" (só cópias do original) na biblioteca
        for p in fallback_copies:
            try:
                os.remove(p)
            except OSError:
                pass
        last = errors[-1]["error"] if errors else "erro desconhecido"
        raise RuntimeError(f"Nenhuma página foi traduzida. Último erro: {last}")

    cbz_path = output_folder.rstrip("/\\") + ".cbz"
    mobile_typesetter.make_cbz_package(output_folder, cbz_path)

    summary = {
        "output": output_folder,
        "cbz": cbz_path,
        "total": total,
        "translated": translated,
        "failed": len(errors),
        "errors": errors[:50],
    }
    if progress_cb:
        progress_cb("done", total, total, summary_message(summary), result=summary)
    return summary


def summary_message(summary):
    """Mensagem final honesta: sucesso total ou parcial com nº de falhas."""
    if summary["failed"]:
        return (f"⚠️ Concluído com falhas: {summary['translated']}/{summary['total']} páginas traduzidas, "
                f"{summary['failed']} ficaram no idioma original. Veja o log.")
    return f"✅ Concluído: {summary['translated']}/{summary['total']} páginas traduzidas."
