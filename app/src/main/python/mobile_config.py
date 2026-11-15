"""
mobile_config.py - Gerenciador de Configurações para Manga Studio Mobile
Armazena chaves de API e diretórios do armazenamento do Android.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import os
import json

CONFIG_DIR_CANDIDATES = [
    "/sdcard/MangaStudio",
    "/storage/emulated/0/MangaStudio",
    os.path.expanduser("~/MangaStudio"),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), ".config"),
]


def get_base_dir():
    """Retorna o diretório onde o arquivo de configuração será persistido no Android."""
    for p in CONFIG_DIR_CANDIDATES:
        try:
            os.makedirs(p, exist_ok=True)
            test_file = os.path.join(p, ".perm_test")
            with open(test_file, "w") as f:
                f.write("ok")
            os.remove(test_file)
            return p
        except Exception:
            continue
    fallback = os.path.dirname(os.path.abspath(__file__))
    return fallback


def get_config_path():
    return os.path.join(get_base_dir(), "mobile_config.json")


def get_default_config():
    """Retorna configurações padrão estritamente adaptadas para smartphones."""
    return {
        "gemini_api_key": "",
        "groq_api_key": "",
        "openrouter_api_key": "",
        "provider_priority": ["gemini", "groq", "openrouter"],
        "target_lang": "pt-BR",
        "input_dir": "/sdcard/MANGAS",
        "output_dir": "/sdcard/MANGAS [PT-BR]",
        "use_local_llm": False,  # Regra Mobile: Proibido Ollama pesado no celular
        "max_image_dim": 1400,   # Resolução ideal para telas de celular e rapidez
        "preserve_lineart": True,
        "auto_cbz": True,
        "auto_reader": True,
    }


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
        # Garante regra mobile inquebrável
        defaults["use_local_llm"] = False
        return defaults
    except Exception as e:
        print(f"[!] Erro ao carregar mobile_config.json: {e}")
        return defaults


def save_config(new_config):
    """Salva as configurações atualizadas no armazenamento do celular."""
    cfg_path = get_config_path()
    try:
        os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
        # Garante regra mobile inquebrável
        new_config["use_local_llm"] = False
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(new_config, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"[!] Erro ao salvar mobile_config.json: {e}")
        return False
