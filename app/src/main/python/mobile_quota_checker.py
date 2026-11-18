"""
mobile_quota_checker.py - Verificador Real de Cotas (Groq, OpenRouter e Gemini)
Consulta em paralelo todas as chaves configuradas e retorna o formato exato
esperado pelo painel Créditos & Cotas (RPD, TPM, saldo e status real).
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

from concurrent.futures import ThreadPoolExecutor
import requests

import mobile_config


def _mask_key(k):
    s = str(k or "").strip()
    if len(s) <= 10:
        return s[:4] + "..." if s else ""
    return f"{s[:8]}...{s[-4:]}"


def _int_hdr(headers, name):
    val = headers.get(name)
    try:
        return int(val) if val is not None else None
    except Exception:
        return None


def _check_groq_single(idx, key, active_model, fallback_model):
    """Testa uma chave Groq nos modelos ativo e fallback coletando headers de cota."""
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    models_to_check = [active_model]
    if fallback_model and fallback_model != active_model:
        models_to_check.append(fallback_model)

    models_out = {}
    any_ok = False
    for m in models_to_check:
        payload = {"model": m, "messages": [{"role": "user", "content": "ok"}], "max_tokens": 1}
        if "qwen3" in m.lower():
            payload["reasoning_effort"] = "none"
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=10)
            rem_req = _int_hdr(r.headers, "x-ratelimit-remaining-requests")
            lim_req = _int_hdr(r.headers, "x-ratelimit-limit-requests")
            rem_tok = _int_hdr(r.headers, "x-ratelimit-remaining-tokens")
            lim_tok = _int_hdr(r.headers, "x-ratelimit-limit-tokens")
            rst_tok = r.headers.get("x-ratelimit-reset-tokens", "")

            if r.status_code == 200:
                any_ok = True
                models_out[m] = {
                    "ok": True,
                    "page_ready": True,
                    "rem_req": rem_req,
                    "lim_req": lim_req,
                    "rem_tok": rem_tok,
                    "lim_tok": lim_tok,
                    "rst_tok": rst_tok,
                    "msg": "",
                }
            elif r.status_code == 401:
                models_out[m] = {
                    "ok": False,
                    "page_ready": False,
                    "is_daily_limit": True,
                    "limit_type": "Chave Inválida (401)",
                    "msg": "Chave não autorizada/revogada (HTTP 401).",
                }
                break
            elif r.status_code == 429:
                models_out[m] = {
                    "ok": False,
                    "page_ready": False,
                    "is_daily_limit": True,
                    "limit_type": "Limite 429",
                    "rem_req": rem_req if rem_req is not None else 0,
                    "lim_req": lim_req,
                    "rem_tok": rem_tok,
                    "lim_tok": lim_tok,
                    "rst_tok": rst_tok,
                    "msg": "Cota atingida no momento (HTTP 429).",
                }
            else:
                models_out[m] = {
                    "ok": False,
                    "page_ready": False,
                    "limit_type": f"HTTP {r.status_code}",
                    "msg": r.text[:100],
                }
        except Exception as e:
            models_out[m] = {"ok": False, "page_ready": False, "limit_type": "Erro Rede", "msg": str(e)[:90]}

    return {"index": idx, "masked_key": _mask_key(key), "ok": any_ok, "models": models_out}


def _check_openrouter_single(idx, key):
    """Consulta saldo e tier de uma chave OpenRouter."""
    try:
        r = requests.get(
            "https://openrouter.ai/api/v1/auth/key",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10,
        )
        if r.status_code == 200:
            data = (r.json() or {}).get("data") or {}
            lim_rem = data.get("limit_remaining")
            usage = data.get("usage", 0) or 0
            is_free = bool(data.get("is_free_tier", lim_rem is None))
            return {
                "index": idx,
                "masked_key": _mask_key(key),
                "ok": True,
                "is_free_tier": is_free,
                "limit_remaining": lim_rem,
                "usage": usage,
                "credits": lim_rem if lim_rem is not None else 0.0,
            }
        return {"index": idx, "masked_key": _mask_key(key), "ok": False, "error": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"index": idx, "masked_key": _mask_key(key), "ok": False, "error": str(e)[:90]}


def _check_gemini_single(idx, key):
    """Valida uma chave Google Gemini."""
    try:
        r = requests.get(f"https://generativelanguage.googleapis.com/v1beta/models?key={key}", timeout=10)
        ok = (r.status_code == 200)
        return {
            "index": idx,
            "masked_key": _mask_key(key),
            "ok": ok,
            "status": "ok" if ok else "error",
            "error": "" if ok else f"HTTP {r.status_code}",
        }
    except Exception as e:
        return {"index": idx, "masked_key": _mask_key(key), "ok": False, "status": "error", "error": str(e)[:90]}


def _collect_keys(cfg, list_field, single_field):
    pool = [str(k).strip() for k in (cfg.get(list_field) or []) if str(k or "").strip()]
    single = str(cfg.get(single_field) or "").strip()
    if single and single not in pool:
        pool.insert(0, single)
    return pool


def build_live_status():
    """Executa sondagem paralela das chaves cadastradas e monta resposta /api/status."""
    cfg = mobile_config.load_config()
    groq_pool = _collect_keys(cfg, "groq_api_keys", "groq_api_key")
    or_pool = _collect_keys(cfg, "openrouter_api_keys", "openrouter_api_key")
    gem_pool = _collect_keys(cfg, "gemini_api_keys", "gemini_api_key")

    active_groq_m = cfg.get("groq_model") or "qwen/qwen3.8-27b"
    fb_groq_m = cfg.get("groq_fallback_model") or "openai/gpt-oss-120b"

    groq_results, or_results, gem_results = [], [], []
    with ThreadPoolExecutor(max_workers=6) as ex:
        f_groq = [ex.submit(_check_groq_single, i + 1, k, active_groq_m, fb_groq_m) for i, k in enumerate(groq_pool)]
        f_or = [ex.submit(_check_openrouter_single, i + 1, k) for i, k in enumerate(or_pool)]
        f_gem = [ex.submit(_check_gemini_single, i + 1, k) for i, k in enumerate(gem_pool)]
        groq_results = [f.result() for f in f_groq]
        or_results = [f.result() for f in f_or]
        gem_results = [f.result() for f in f_gem]

    ready_active = sum(1 for g in groq_results if (g["models"].get(active_groq_m) or {}).get("ok"))
    any_ready = sum(1 for g in groq_results if g.get("ok"))
    tot_rem = sum(int((g["models"].get(active_groq_m) or {}).get("rem_req") or 0) for g in groq_results)
    tot_lim = sum(int((g["models"].get(active_groq_m) or {}).get("lim_req") or 0) for g in groq_results)

    return {
        "groq": {
            "configured": bool(groq_pool),
            "keys": groq_results,
            "active_model": active_groq_m,
            "fallback_model": fb_groq_m,
            "ready_keys_count": ready_active,
            "any_model_ready_keys": any_ready,
            "total_active_remaining": tot_rem,
            "total_active_limit": tot_lim,
            "total_qwen_remaining": tot_rem,
            "total_qwen_limit": tot_lim,
            "deep_checked": True,
        },
        "openrouter": {
            "configured": bool(or_pool),
            "keys": or_results,
            "active_model": cfg.get("openrouter_model") or "nvidia/nemotron-3.5-lightning:free",
        },
        "gemini": {
            "configured": bool(gem_pool),
            "keys": gem_results,
            "active_model": cfg.get("gemini_model") or "gemini-3.1-flash-lite",
        },
        "ollama": {
            "status": "disabled_mobile",
            "message": "Desativado para celulares (usando Groq / OpenRouter / Gemini Cloud)",
            "models": [],
            "vision_models": [],
        },
        "vision": {
            "provider": cfg.get("vision_provider") or ("gemini" if gem_pool else ("groq" if groq_pool else "openrouter")),
            "gemini_model": cfg.get("gemini_model") or "gemini-3.1-flash-lite",
            "groq_vision_model": cfg.get("groq_vision_model") or "qwen/qwen3.8-27b",
            "openrouter_vision_model": cfg.get("openrouter_vision_model") or "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
            "ollama_vision_model": "",
        },
        "runtime_warnings": [],
    }
