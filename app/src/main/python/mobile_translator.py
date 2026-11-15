"""
mobile_translator.py - Motor de Tradução Leve para Smartphone (APIs de Nuvem)
Combina detecção visual e tradução via Gemini Vision / Groq com zero consumo de RAM.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import os
import re
import json
import base64
import requests
import cv2
import numpy as np
from PIL import Image

import mobile_config
import mobile_typesetter


def encode_image_base64(img_path, max_dim=1400):
    """Redimensiona se necessário e codifica a imagem em base64 para envio à API."""
    im = cv2.imread(img_path)
    if im is None:
        return None, (0, 0)
    h, w = im.shape[:2]
    if max(h, w) > max_dim:
        scale = max_dim / float(max(h, w))
        nw, nh = int(w * scale), int(h * scale)
        im = cv2.resize(im, (nw, nh), interpolation=cv2.INTER_AREA)
    is_ok, buf = cv2.imencode(".jpg", im, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not is_ok:
        return None, (h, w)
    return base64.b64encode(buf.tobytes()).decode("utf-8"), (h, w)


def call_gemini_vision(img_b64, api_key):
    """Chama a API do Google Gemini Vision para detectar balões e traduzir em 1 chamada."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    system_prompt = (
        "Você é um tradutor especialista de mangás para Português do Brasil (PT-BR). "
        "Analise a página de mangá fornecida. Detecte todos os balões de fala japoneses legíveis. "
        "Retorne ESTRITAMENTE um JSON no formato: "
        '[{"box_2d": [ymin, xmin, ymax, xmax], "translation": "texto traduzido em PT-BR"}] '
        "As coordenadas ymin, xmin, ymax, xmax devem estar normalizadas entre 0 e 1000. "
        "Não inclua markdown extra, apenas o JSON válido."
    )

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": system_prompt},
                    {
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": img_b64
                        }
                    }
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "response_mime_type": "application/json"
        }
    }

    resp = requests.post(url, json=payload, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"Erro Gemini API ({resp.status_code}): {resp.text[:200]}")

    data = resp.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        return json.loads(match.group(0))
    return json.loads(text)


def process_single_page(img_path, out_path, config):
    """Processa uma página: envia para IA, limpa balões e diagramação em PT-BR."""
    gemini_key = config.get("gemini_api_key", "").strip()
    if not gemini_key:
        raise ValueError("Chave de API do Gemini não configurada. Configure no menu de chaves!")

    b64, (orig_h, orig_w) = encode_image_base64(img_path, config.get("max_image_dim", 1400))
    if not b64:
        raise ValueError(f"Não foi possível ler a imagem: {img_path}")

    bubbles = call_gemini_vision(b64, gemini_key)
    img_cv = cv2.imread(img_path)
    real_h, real_w = img_cv.shape[:2]

    # Passo 1: Limpeza cirúrgica de cada balão
    for item in bubbles:
        box = item.get("box_2d", [])
        if len(box) == 4:
            ymin = int((box[0] / 1000.0) * real_h)
            xmin = int((box[1] / 1000.0) * real_w)
            ymax = int((box[2] / 1000.0) * real_h)
            xmax = int((box[3] / 1000.0) * real_w)
            img_cv = mobile_typesetter.clean_balloon_area(img_cv, xmin, ymin, xmax, ymax)

    # Passo 2: Diagramação com tipografia responsiva
    img_pil = Image.fromarray(cv2.cvtColor(img_cv, cv2.COLOR_BGR2RGB))
    for item in bubbles:
        box = item.get("box_2d", [])
        trans = item.get("translation", "").strip()
        if len(box) == 4 and trans:
            ymin = int((box[0] / 1000.0) * real_h)
            xmin = int((box[1] / 1000.0) * real_w)
            ymax = int((box[2] / 1000.0) * real_h)
            xmax = int((box[3] / 1000.0) * real_w)
            img_pil = mobile_typesetter.render_dialogue_balloon(img_pil, trans, xmin, ymin, xmax, ymax)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img_pil.save(out_path, quality=95)
    return len(bubbles)


def translate_manga_folder(input_folder, output_folder=None, progress_cb=None):
    """Traduz todas as páginas de uma pasta de mangá no armazenamento do celular."""
    cfg = mobile_config.load_config()
    exts = (".jpg", ".jpeg", ".png", ".webp")
    files = sorted([f for f in os.listdir(input_folder) if f.lower().endswith(exts)])
    if not files:
        raise ValueError(f"Nenhuma imagem encontrada em: {input_folder}")

    if not output_folder:
        base_name = os.path.basename(input_folder.rstrip("/\\"))
        output_folder = os.path.join(cfg.get("output_dir", "/sdcard/MANGAS [PT-BR]"), f"{base_name} [PT-BR]")

    os.makedirs(output_folder, exist_ok=True)
    total = len(files)

    for idx, fname in enumerate(files):
        in_p = os.path.join(input_folder, fname)
        out_p = os.path.join(output_folder, f"{os.path.splitext(fname)[0]}.jpg")
        if progress_cb:
            progress_cb("translating", idx + 1, total, f"Traduzindo página {idx + 1}/{total} ({fname})...")

        try:
            process_single_page(in_p, out_p, cfg)
        except Exception as e:
            print(f"[!] Erro ao traduzir {fname}: {e}")

    # Gera CBZ e leitor offline
    cbz_path = os.path.join(os.path.dirname(output_folder), f"{os.path.basename(output_folder)}.cbz")
    mobile_typesetter.make_cbz_package(output_folder, cbz_path)
    mobile_typesetter.make_offline_reader(output_folder, os.path.basename(output_folder))

    if progress_cb:
        progress_cb("done", total, total, "Tradução concluída com sucesso!", result={"cbz": cbz_path})

    return output_folder
