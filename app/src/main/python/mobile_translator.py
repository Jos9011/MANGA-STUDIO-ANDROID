"""
mobile_translator.py - Motor de Tradução para Smartphone (APIs Cloud)
Suporta Groq Vision, Gemini Vision e OpenRouter Vision com rotação de chaves.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import base64
import io
import json
import os
import re
import shutil
import requests
from PIL import Image

import mobile_config
import mobile_typesetter

PROMPT = (
    "Você é um tradutor especialista de mangás para Português do Brasil (PT-BR). "
    "Analise a página de mangá. Detecte todos os balões de fala japoneses legíveis. "
    "Retorne ESTRITAMENTE um JSON no formato: "
    '[{"box_2d": [ymin, xmin, ymax, xmax], "translation": "texto traduzido em PT-BR"}]. '
    "As coordenadas ymin, xmin, ymax, xmax devem estar normalizadas entre 0 e 1000. "
    "Se não houver balões, retorne []. Retorne apenas o JSON, sem markdown ou texto extra."
)


def encode_image_base64(img_path, max_dim=1400):
    """Redimensiona e codifica a imagem em base64 usando Pillow."""
    with Image.open(img_path) as im:
        im = im.convert("RGB")
        w, h = im.size
        if max(w, h) > max_dim:
            scale = max_dim / float(max(w, h))
            im = im.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85)
        return base64.b64encode(buf.getvalue()).decode("utf-8"), (h, w)


def extract_json_bubbles(text):
    """Extrai e valida a lista de balões em JSON a partir da resposta da IA."""
    if not text:
        return []
    clean = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    clean = re.sub(r"```json\s*", "", clean)
    clean = re.sub(r"```\s*", "", clean).strip()

    match = re.search(r"\[\s*\{.*?\}\s*\]", clean, re.DOTALL)
    raw = match.group(0) if match else clean
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for v in data.values():
                if isinstance(v, list):
                    return v
    except Exception:
        pass
    return []


def call_groq_vision(img_b64, keys, model=None):
    """Executa detecção e tradução visual via Groq Vision com rotação de chaves."""
    model = model or "qwen/qwen3.8-27b"
    url = "https://api.groq.com/openai/v1/chat/completions"
    last_err = None

    for key in keys:
        if not key or not str(key).strip():
            continue
        try:
            payload = {
                "model": model,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": PROMPT},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
                    ]
                }],
                "temperature": 0.1,
                "max_tokens": 1024
            }
            if "qwen3" in model.lower():
                payload["reasoning_effort"] = "none"

            resp = requests.post(url, json=payload, headers={"Authorization": f"Bearer {key.strip()}"}, timeout=45)
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return extract_json_bubbles(content)
            last_err = f"Groq {resp.status_code}: {resp.text[:150]}"
        except Exception as e:
            last_err = str(e)
            continue
    raise RuntimeError(f"Falha em todas as chaves Groq: {last_err}")


def call_gemini_vision(img_b64, keys, model=None):
    """Executa detecção e tradução visual via Google Gemini Vision."""
    model = model or "gemini-1.5-flash"
    last_err = None

    for key in keys:
        if not key or not str(key).strip():
            continue
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key.strip()}"
            payload = {
                "contents": [{"parts": [
                    {"text": PROMPT},
                    {"inline_data": {"mime_type": "image/jpeg", "data": img_b64}}
                ]}],
                "generationConfig": {"temperature": 0.1, "response_mime_type": "application/json"}
            }
            resp = requests.post(url, json=payload, timeout=40)
            if resp.status_code == 200:
                data = resp.json()
                content = data["candidates"][0]["content"]["parts"][0]["text"]
                return extract_json_bubbles(content)
            last_err = f"Gemini {resp.status_code}: {resp.text[:150]}"
        except Exception as e:
            last_err = str(e)
            continue
    raise RuntimeError(f"Falha em todas as chaves Gemini: {last_err}")


def call_openrouter_vision(img_b64, keys, model=None):
    """Executa detecção e tradução visual via OpenRouter Vision."""
    model = model or "google/gemma-4-31b-it:free"
    url = "https://openrouter.ai/api/v1/chat/completions"
    last_err = None

    for key in keys:
        if not key or not str(key).strip():
            continue
        try:
            payload = {
                "model": model,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": PROMPT},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
                    ]
                }],
                "temperature": 0.1,
                "max_tokens": 1024
            }
            headers = {"Authorization": f"Bearer {key.strip()}", "HTTP-Referer": "https://mangastudio.local"}
            resp = requests.post(url, json=payload, headers=headers, timeout=45)
            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"]
                return extract_json_bubbles(content)
            last_err = f"OpenRouter {resp.status_code}: {resp.text[:150]}"
        except Exception as e:
            last_err = str(e)
            continue
    raise RuntimeError(f"Falha em todas as chaves OpenRouter: {last_err}")


def call_vision_api(img_b64, cfg):
    """Roteia a requisição visual para o provedor configurado com fallback automático."""
    groq_keys = [k for k in cfg.get("groq_api_keys", []) if k]
    if cfg.get("groq_api_key") and cfg["groq_api_key"] not in groq_keys:
        groq_keys.insert(0, cfg["groq_api_key"])

    gemini_keys = [k for k in cfg.get("gemini_api_keys", []) if k]
    if cfg.get("gemini_api_key") and cfg["gemini_api_key"] not in gemini_keys:
        gemini_keys.insert(0, cfg["gemini_api_key"])

    or_keys = [k for k in cfg.get("openrouter_api_keys", []) if k]
    if cfg.get("openrouter_api_key") and cfg["openrouter_api_key"] not in or_keys:
        or_keys.insert(0, cfg["openrouter_api_key"])

    provider = str(cfg.get("provider", "groq")).lower().strip()
    if provider == "groq" and groq_keys:
        return call_groq_vision(img_b64, groq_keys, cfg.get("groq_vision_model") or cfg.get("groq_model"))
    if provider == "gemini" and gemini_keys:
        return call_gemini_vision(img_b64, gemini_keys, cfg.get("gemini_vision_model") or cfg.get("gemini_model"))
    if provider == "openrouter" and or_keys:
        return call_openrouter_vision(img_b64, or_keys, cfg.get("openrouter_vision_model") or cfg.get("openrouter_model"))

    # Fallback automático por chaves disponíveis
    if groq_keys:
        return call_groq_vision(img_b64, groq_keys, cfg.get("groq_vision_model") or cfg.get("groq_model"))
    if gemini_keys:
        return call_gemini_vision(img_b64, gemini_keys, cfg.get("gemini_vision_model") or cfg.get("gemini_model"))
    if or_keys:
        return call_openrouter_vision(img_b64, or_keys, cfg.get("openrouter_vision_model") or cfg.get("openrouter_model"))

    raise ValueError("Nenhuma chave de API configurada! Adicione sua chave Groq, Gemini ou OpenRouter em Configurações.")


def process_single_page(img_path, out_path, config):
    """Processa uma página: envia para IA, limpa balões e renderiza texto traduzido."""
    b64, (orig_h, orig_w) = encode_image_base64(img_path, config.get("max_image_dim", 1400))
    bubbles = call_vision_api(b64, config)

    img_pil = Image.open(img_path).convert("RGB")
    real_w, real_h = img_pil.size

    for item in bubbles:
        box = item.get("box_2d", [])
        if len(box) == 4:
            ymin, xmin = int((box[0] / 1000.0) * real_h), int((box[1] / 1000.0) * real_w)
            ymax, xmax = int((box[2] / 1000.0) * real_h), int((box[3] / 1000.0) * real_w)
            img_pil = mobile_typesetter.clean_balloon_area(img_pil, xmin, ymin, xmax, ymax)

    for item in bubbles:
        box = item.get("box_2d", [])
        trans = item.get("translation", "").strip()
        if len(box) == 4 and trans:
            ymin, xmin = int((box[0] / 1000.0) * real_h), int((box[1] / 1000.0) * real_w)
            ymax, xmax = int((box[2] / 1000.0) * real_h), int((box[3] / 1000.0) * real_w)
            img_pil = mobile_typesetter.render_dialogue_balloon(img_pil, trans, xmin, ymin, xmax, ymax)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img_pil.save(out_path, "JPEG", quality=92)
    return len(bubbles)


def translate_manga_folder(input_folder, output_folder=None, progress_cb=None):
    """Traduz todas as páginas de uma pasta de mangá com resiliência total a erros."""
    cfg = mobile_config.load_config()
    exts = (".jpg", ".jpeg", ".png", ".webp")
    files = sorted([f for f in os.listdir(input_folder) if f.lower().endswith(exts)])
    if not files:
        raise ValueError(f"Nenhuma imagem encontrada em: {input_folder}")

    # Validação antecipada de chaves para evitar processamento inútil
    has_keys = bool(
        cfg.get("groq_api_keys") or cfg.get("groq_api_key") or
        cfg.get("gemini_api_keys") or cfg.get("gemini_api_key") or
        cfg.get("openrouter_api_keys") or cfg.get("openrouter_api_key")
    )
    if not has_keys:
        raise ValueError("Nenhuma chave de API configurada! Adicione uma chave em Configurações.")

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
            if not os.path.exists(out_p):
                try:
                    with Image.open(in_p) as im:
                        im.convert("RGB").save(out_p, "JPEG", quality=90)
                except Exception as save_err:
                    print(f"[!] Erro no fallback de cópia {fname}: {save_err}")

    clean_out = output_folder.rstrip("/\\")
    cbz_path = clean_out + ".cbz"
    mobile_typesetter.make_cbz_package(output_folder, cbz_path)
    mobile_typesetter.make_offline_reader(output_folder, os.path.basename(output_folder))

    if progress_cb:
        progress_cb("done", total, total, "Tradução concluída com sucesso!", result={"cbz": cbz_path})

    return output_folder
