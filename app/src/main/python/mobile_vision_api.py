"""
mobile_vision_api.py - Chamadas de IA Vision (Gemini, Groq, OpenRouter) com fallback entre provedores
Detecta respostas cortadas/bloqueadas e tenta o próximo provedor em vez de falhar em silêncio.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import json
import re
import requests

PROMPT = (
    "Você é um tradutor especialista de mangás/quadrinhos para Português do Brasil (PT-BR). "
    "Analise a página e detecte todos os balões de fala legíveis (japonês, chinês, coreano ou inglês). "
    "Agrupe todas as linhas de um mesmo balão em UM único item. Em falas divididas em múltiplos balões contíguos, preserve o sentido contínuo. "
    "Traduza sempre o pronome inglês 'I' (sozinho ou na frase) como 'Eu' — NUNCA deixe 'I' solto em inglês. "
    "Ignore letras soltas vazadas de scans antigos em balões asiáticos. "
    "Retorne ESTRITAMENTE um JSON: "
    '[{"box_2d": [ymin, xmin, ymax, xmax], "translation": "texto traduzido em PT-BR"}]. '
    "Coordenadas normalizadas entre 0 e 1000 (0,0 = canto superior esquerdo; ordem ymin, xmin, ymax, xmax). "
    "Se não houver falas, retorne []. Apenas JSON válido."
)

MAX_OUTPUT_TOKENS = 4096
PROVIDER_ORDER = ("gemini", "groq", "openrouter")  # Gemini primeiro: coordenadas box_2d nativas


class VisionResponseError(RuntimeError):
    """Resposta recebida, porém inutilizável (cortada, bloqueada ou não-JSON)."""


def parse_bubbles(text):
    """Converte a resposta da IA em lista de balões. Lança VisionResponseError se não for JSON válido."""
    if text is None:
        raise VisionResponseError("Resposta vazia da IA.")
    clean = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    clean = re.sub(r"```json\s*", "", clean)
    clean = re.sub(r"```\s*", "", clean).strip()
    if clean in ("", "[]"):
        return []

    match = re.search(r"\[\s*\{.*\}\s*\]", clean, re.DOTALL)
    raw = match.group(0) if match else clean
    try:
        data = json.loads(raw)
    except Exception:
        raise VisionResponseError(f"Resposta da IA não é JSON válido (pode ter sido cortada): {clean[:80]!r}")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                return v
    raise VisionResponseError("Resposta da IA não contém lista de balões.")


def extract_json_bubbles(text):
    """Compatibilidade: igual a parse_bubbles, mas devolve [] em vez de lançar erro."""
    try:
        return parse_bubbles(text)
    except VisionResponseError:
        return []


def _openai_style_content(data, provider):
    """Extrai o texto de uma resposta estilo OpenAI e detecta corte por limite de tokens."""
    choice = (data.get("choices") or [{}])[0]
    if choice.get("finish_reason") == "length":
        raise VisionResponseError(f"{provider}: resposta cortada pelo limite de tokens.")
    return (choice.get("message") or {}).get("content")


def call_groq_vision(img_b64, keys, model=None):
    """Executa detecção e tradução visual via Groq Vision com rotação de chaves."""
    model = model or "qwen/qwen3.8-27b"
    url = "https://api.groq.com/openai/v1/chat/completions"
    last_err = None
    for key in keys:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
            ]}],
            "temperature": 0.1,
            "max_tokens": MAX_OUTPUT_TOKENS,
        }
        if "qwen3" in model.lower():
            payload["reasoning_effort"] = "none"
        try:
            resp = requests.post(url, json=payload, headers={"Authorization": f"Bearer {key}"}, timeout=60)
        except Exception as e:
            last_err = f"Groq conexão: {e}"
            continue
        if resp.status_code == 200:
            return parse_bubbles(_openai_style_content(resp.json(), "Groq"))
        last_err = f"Groq {resp.status_code}: {resp.text[:150]}"
    raise RuntimeError(f"Falha em todas as chaves Groq ({model}): {last_err}")


def call_gemini_vision(img_b64, keys, model=None):
    """Executa detecção e tradução visual via Google Gemini Vision."""
    model = model or "gemini-3.1-flash-lite"
    last_err = None
    for key in keys:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        payload = {
            "contents": [{"parts": [
                {"text": PROMPT},
                {"inline_data": {"mime_type": "image/jpeg", "data": img_b64}},
            ]}],
            "generationConfig": {
                "temperature": 0.1,
                "response_mime_type": "application/json",
                "maxOutputTokens": MAX_OUTPUT_TOKENS * 2,
            },
        }
        try:
            resp = requests.post(url, json=payload, headers={"x-goog-api-key": key}, timeout=60)
        except Exception as e:
            last_err = f"Gemini conexão: {e}"
            continue
        if resp.status_code != 200:
            last_err = f"Gemini {resp.status_code}: {resp.text[:150]}"
            continue

        data = resp.json()
        cands = data.get("candidates") or []
        if not cands:
            reason = (data.get("promptFeedback") or {}).get("blockReason", "sem candidatos")
            raise VisionResponseError(f"Gemini bloqueou a página ({reason}).")
        cand = cands[0]
        finish = cand.get("finishReason", "")
        if finish == "MAX_TOKENS":
            raise VisionResponseError("Gemini: resposta cortada pelo limite de tokens.")
        parts = (cand.get("content") or {}).get("parts") or []
        if not parts:
            raise VisionResponseError(f"Gemini não retornou texto (finishReason={finish or '?'}).")
        return parse_bubbles(parts[0].get("text"))
    raise RuntimeError(f"Falha em todas as chaves Gemini ({model}): {last_err}")


def call_openrouter_vision(img_b64, keys, model=None):
    """Executa detecção e tradução visual via OpenRouter Vision."""
    model = model or "google/gemma-4-31b-it:free"
    url = "https://openrouter.ai/api/v1/chat/completions"
    last_err = None
    for key in keys:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
            ]}],
            "temperature": 0.1,
            "max_tokens": MAX_OUTPUT_TOKENS,
        }
        headers = {"Authorization": f"Bearer {key}", "HTTP-Referer": "https://mangastudio.local"}
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=60)
        except Exception as e:
            last_err = f"OpenRouter conexão: {e}"
            continue
        if resp.status_code == 200:
            return parse_bubbles(_openai_style_content(resp.json(), "OpenRouter"))
        last_err = f"OpenRouter {resp.status_code}: {resp.text[:150]}"
    raise RuntimeError(f"Falha em todas as chaves OpenRouter ({model}): {last_err}")


_CALLS = {
    "gemini": (call_gemini_vision, "gemini_vision_model", "gemini_model"),
    "groq": (call_groq_vision, "groq_vision_model", "groq_model"),
    "openrouter": (call_openrouter_vision, "openrouter_vision_model", "openrouter_model"),
}


def collect_keys(cfg, provider):
    """Junta chave singular + lista, sem duplicatas nem vazias."""
    keys = []
    for k in [cfg.get(f"{provider}_api_key")] + list(cfg.get(f"{provider}_api_keys") or []):
        k = str(k or "").strip()
        if k and k not in keys:
            keys.append(k)
    return keys


def provider_order(cfg):
    """Provedor escolhido primeiro; os demais com chave entram como fallback."""
    pref = str(cfg.get("provider", "auto")).lower().strip()
    order = list(PROVIDER_ORDER)
    if pref in order:
        order.remove(pref)
        order.insert(0, pref)
    return order


def call_vision_api(img_b64, cfg):
    """Roteia para o provedor configurado e recua para os outros provedores com chave se ele falhar."""
    errors = []
    for prov in provider_order(cfg):
        keys = collect_keys(cfg, prov)
        if not keys:
            continue
        fn, vision_field, model_field = _CALLS[prov]
        try:
            return fn(img_b64, keys, cfg.get(vision_field) or cfg.get(model_field))
        except Exception as e:
            errors.append(str(e))
    if not errors:
        raise ValueError("Nenhuma chave de API configurada! Adicione sua chave Groq, Gemini ou OpenRouter em Configurações.")
    raise RuntimeError(" | ".join(errors))
