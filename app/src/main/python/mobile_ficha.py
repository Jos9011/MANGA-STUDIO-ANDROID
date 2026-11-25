"""
mobile_ficha.py - Ficha da Obra e Líder do capítulo no celular (Fase 1, adaptada ao app)

No PC o OCR roda antes da tradução, então o Líder lê o capítulo e atualiza a ficha ANTES de
traduzir. No celular a IA Vision lê e traduz cada página numa chamada só. Por isso aqui:
  1. antes do capítulo: carrega a ficha da obra e anexa ao prompt da IA Vision;
  2. a IA Vision devolve também o texto original de cada balão;
  3. no fim do capítulo: o Líder lê esses originais e atualiza a ficha para os próximos.

Os módulos ficha_obra.py, ficha_caminho.py e lider_capitulo.py são cópias idênticas dos do PC
(SKILL-TRADUCAO-MANGA); mantenha-os sincronizados. A ficha usa o mesmo arquivo
(.fichas_obra/<obra>.json) e o mesmo formato.
Qualquer erro aqui é engolido: a ficha nunca pode quebrar a tradução.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import os
import requests

import ficha_caminho
import ficha_obra
import lider_capitulo
from mobile_vision_api import collect_keys

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def _openai_chat(url, key, model, messages, max_tokens, extra_headers=None):
    payload = {"model": model, "messages": messages, "temperature": 0.0, "max_tokens": max_tokens}
    if "gpt-oss" in model.lower():
        payload["reasoning_effort"] = "low"
    elif "qwen3" in model.lower():
        payload["reasoning_effort"] = "none"
    headers = {"Authorization": f"Bearer {key}"}
    headers.update(extra_headers or {})
    resp = requests.post(url, json=payload, headers=headers, timeout=90)
    if resp.status_code != 200:
        raise RuntimeError(f"{resp.status_code}: {resp.text[:120]}")
    choice = (resp.json().get("choices") or [{}])[0]
    return (choice.get("message") or {}).get("content") or ""


def _gemini_chat(key, model, messages, max_tokens):
    system = "\n".join(m["content"] for m in messages if m.get("role") == "system")
    user = "\n".join(m["content"] for m in messages if m.get("role") != "system")
    payload = {
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": max_tokens * 2,
                             "response_mime_type": "application/json"},
    }
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    resp = requests.post(GEMINI_URL.format(model=model), json=payload, headers={"x-goog-api-key": key}, timeout=90)
    if resp.status_code != 200:
        raise RuntimeError(f"{resp.status_code}: {resp.text[:120]}")
    cands = resp.json().get("candidates") or []
    parts = ((cands[0].get("content") or {}).get("parts") or []) if cands else []
    return parts[0].get("text", "") if parts else ""


def chat_text(messages, cfg, max_tokens=1500, groq_model=None):
    """Chamada de texto (sem imagem) para o Líder: Groq -> Gemini -> OpenRouter. Devolve '' se tudo falhar."""
    groq_model = groq_model or cfg.get("lider_model") or lider_capitulo.DEFAULT_LEADER_MODEL
    attempts = []
    for key in collect_keys(cfg, "groq"):
        attempts.append(lambda k=key: _openai_chat(GROQ_URL, k, groq_model, messages, max_tokens))
    gem_model = cfg.get("gemini_model") or "gemini-3.1-flash-lite"
    for key in collect_keys(cfg, "gemini"):
        attempts.append(lambda k=key: _gemini_chat(k, gem_model, messages, max_tokens))
    or_model = cfg.get("openrouter_model") or "nvidia/nemotron-3.5-lightning:free"
    for key in collect_keys(cfg, "openrouter"):
        attempts.append(lambda k=key: _openai_chat(OPENROUTER_URL, k, or_model, messages, max_tokens,
                                                   {"HTTP-Referer": "https://mangastudio.local"}))
    for attempt in attempts:
        try:
            text = attempt()
            if text and text.strip():
                return text
        except Exception as e:
            print(f"[Líder] Provedor falhou: {e}")
    return ""


def make_execute_fn(cfg):
    """Adapta chat_text à assinatura que o lider_capitulo espera (a mesma do roteador do PC)."""
    def execute(messages, engine_opts=None, is_adult=True, max_tokens=1500, **_):
        model = (engine_opts or {}).get("preferred_model")
        return chat_text(messages, cfg, max_tokens=max_tokens, groq_model=model)
    return execute


def load_chapter_ficha(chapter_dir, cfg):
    """Carrega a ficha da obra deste capítulo. None se desligada ou em caso de erro."""
    try:
        if not ficha_obra.is_enabled(cfg):
            return None
        d = os.path.abspath(str(chapter_dir).rstrip("/\\"))
        path = ficha_caminho.resolve_ficha_path(d)
        obra = ficha_caminho.obra_display_name(d, path, fallback=os.path.basename(d))
        return {"ficha": ficha_obra.load_ficha(path, obra=obra), "path": path}
    except Exception as e:
        print(f"[Ficha] Não foi possível carregar a ficha: {e}")
        return None


def prompt_block(ctx):
    """Bloco da ficha para o prompt da IA Vision ('' se não houver nada)."""
    if not ctx:
        return ""
    block = ficha_obra.build_prompt_block(ctx.get("ficha"))
    if not block:
        return ""
    return block + "Use EXATAMENTE esses nomes e concorde pronomes/adjetivos com o gênero indicado.\n"


def update_after_chapter(chapter_dir, originals, cfg, log=print):
    """Roda o Líder com os textos originais do capítulo e salva a ficha. Devolve True se salvou."""
    try:
        if not originals or not lider_capitulo.leader_enabled(cfg):
            return False
        d = os.path.abspath(str(chapter_dir).rstrip("/\\"))
        ctx = lider_capitulo.run_for_chapter(
            d, os.path.basename(d), originals, {"active_engine": "groq"}, make_execute_fn(cfg),
            config=cfg, src_lang="auto", force=False, log=log,
        )
        return lider_capitulo.save_if_changed(ctx)
    except Exception as e:
        log(f"[!] [Líder] Etapa ignorada por erro: {e}")
        return False
