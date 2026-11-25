"""
mobile_config.py - Gerenciador de Configurações para Manga Studio Mobile
Armazena chaves de API e diretórios do armazenamento do Android.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import json
import os
import re
import tempfile


def get_base_dir():
    """Retorna diretório com permissão total garantida de escrita no Android."""
    candidates = [
        "/data/data/com.mangastudio.mobile/files",
        "/data/user/0/com.mangastudio.mobile/files",
        os.path.join(tempfile.gettempdir(), "mangastudio_data"),
        os.path.expanduser("~/MangaStudio"),
        "/storage/emulated/0/Download",
    ]
    for p in candidates:
        try:
            os.makedirs(p, exist_ok=True)
            test_file = os.path.join(p, ".perm_test")
            with open(test_file, "w") as f:
                f.write("ok")
            os.remove(test_file)
            return p
        except Exception:
            continue
    fallback = os.path.join(tempfile.gettempdir(), "mangastudio_data")
    os.makedirs(fallback, exist_ok=True)
    return fallback


def get_config_path():
    return os.path.join(get_base_dir(), "mobile_config.json")


def get_default_config():
    """Retorna configurações padrão estritamente adaptadas para smartphones."""
    return {
        "gemini_api_key": "",
        "gemini_api_keys": [],
        "groq_api_key": "",
        "groq_api_keys": [],
        "openrouter_api_key": "",
        "openrouter_api_keys": [],
        "provider": "auto",
        "groq_model": "qwen/qwen3.8-27b",
        "gemini_model": "gemini-3.1-flash-lite",
        "openrouter_model": "nvidia/nemotron-3.5-lightning:free",
        "target_lang": "pt-BR",
        "input_dir": "/sdcard/MANGAS",
        "output_dir": "/sdcard/MANGAS [PT-BR]",
        "raw_mangas_dir": "/sdcard/MANGAS",
        "translated_mangas_dir": "/sdcard/MANGAS [PT-BR]",
        "gdrive_root_folder": "MANGAS",
        "use_local_llm": False,  # Regra Mobile: Proibido Ollama pesado no celular
        "max_image_dim": 1400,
        "preserve_lineart": True,
        "auto_cbz": True,
        "auto_reader": True,
    }


def sanitize_profile_config(cfg):
    """Sanitiza caminhos e normaliza chaves vindas de perfil do PC para o Android."""
    # 1. Ignora caminhos de disco do Windows (ex: C:\Users\...)
    for path_key in ("raw_mangas_dir", "translated_mangas_dir", "input_dir", "output_dir"):
        val = str(cfg.get(path_key) or "")
        if re.match(r"^[a-zA-Z]:", val) or "\\" in val:
            cfg.pop(path_key, None)

    # 2. Sincroniza diretórios no Android
    in_d = cfg.get("raw_mangas_dir") or cfg.get("input_dir") or "/sdcard/MANGAS"
    out_d = cfg.get("translated_mangas_dir") or cfg.get("output_dir") or "/sdcard/MANGAS [PT-BR]"
    cfg["input_dir"] = in_d
    cfg["raw_mangas_dir"] = in_d
    cfg["output_dir"] = out_d
    cfg["translated_mangas_dir"] = out_d

    # 3. Sincroniza chaves de API (singular <-> plural)
    for prov in ("groq", "gemini", "openrouter"):
        k_single = f"{prov}_api_key"
        k_list = f"{prov}_api_keys"
        keys = list(cfg.get(k_list) or [])
        if not keys and cfg.get(k_single):
            keys = [cfg.get(k_single)]
        if keys:
            cfg[k_list] = keys
            cfg[k_single] = keys[0]

    # 4. Regra Mobile estrita
    cfg["use_local_llm"] = False
    if cfg.get("provider") == "ollama":
        if cfg.get("groq_api_key"):
            cfg["provider"] = "groq"
        elif cfg.get("gemini_api_key"):
            cfg["provider"] = "gemini"
        elif cfg.get("openrouter_api_key"):
            cfg["provider"] = "openrouter"
        else:
            cfg["provider"] = "auto"
    return cfg


def load_config():
    """Carrega as configurações salvas ou mescla com as padrões."""
    defaults = get_default_config()
    cfg_path = get_config_path()
    if not os.path.exists(cfg_path):
        save_config(defaults)
        return defaults

    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            saved = json.load(f)
        defaults.update(saved)
        return sanitize_profile_config(defaults)
    except Exception as e:
        print(f"[!] Erro ao carregar mobile_config.json: {e}")
        return defaults


def save_config(new_config):
    """Salva as configurações atualizadas no armazenamento do celular."""
    cfg_path = get_config_path()
    try:
        os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
        sanitized = sanitize_profile_config(new_config)
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(sanitized, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"[!] Erro ao salvar mobile_config.json: {e}")
        return False
