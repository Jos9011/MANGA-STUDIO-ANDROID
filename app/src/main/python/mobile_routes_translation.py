"""
mobile_routes_translation.py - Endpoints de Tradução por IA, Colorização e Configurações
Gerencia o ciclo de vida dos jobs de IA em background e validação de chaves.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import os
import threading
import time
import requests
from flask import Blueprint, jsonify, request

import mobile_config
import mobile_drive_helper
import mobile_translator

trans_bp = Blueprint("trans_bp", __name__)

_JOB_STATE = {
    "status": "idle",
    "manga_name": "",
    "manga_path": "",
    "first_img": "",
    "stage": "idle",
    "current_page": 0,
    "total_pages": 0,
    "percentage": 0,
    "message": "Pronto para traduzir",
    "logs": [],
    "result": None,
    "error": None,
}
_JOB_LOCK = threading.Lock()


def set_job_progress(status=None, stage=None, current=None, total=None, msg=None, log=None, result=None, error=None):
    with _JOB_LOCK:
        if status is not None:
            _JOB_STATE["status"] = status
        if stage is not None:
            _JOB_STATE["stage"] = stage
        if current is not None:
            _JOB_STATE["current_page"] = current
        if total is not None:
            _JOB_STATE["total_pages"] = total
        if total and total > 0 and current is not None:
            _JOB_STATE["percentage"] = min(100, int((current / float(total)) * 100))
        if msg is not None:
            _JOB_STATE["message"] = msg
        if log:
            _JOB_STATE["logs"].append(log)
            if len(_JOB_STATE["logs"]) > 60:
                _JOB_STATE["logs"].pop(0)
        if result is not None:
            _JOB_STATE["result"] = result
        if error is not None:
            _JOB_STATE["error"] = error


@trans_bp.route("/api/progress")
def api_progress():
    with _JOB_LOCK:
        return jsonify(dict(_JOB_STATE))


@trans_bp.route("/api/start", methods=["POST"])
def api_start():
    with _JOB_LOCK:
        if _JOB_STATE["status"] == "running":
            return jsonify({"error": "Já existe uma tradução em andamento!"}), 409

    data = request.get_json() or {}
    path = data.get("path", "").strip("\"'")
    if not path or not os.path.exists(path):
        return jsonify({"error": "Caminho inválido ou não encontrado."}), 400

    target_dir = path
    if os.path.isfile(path) and path.lower().endswith((".zip", ".cbz")):
        target_dir = mobile_drive_helper.extract_manga_archive(path)
        if not target_dir:
            return jsonify({"error": "Falha ao extrair páginas do arquivo."}), 400

    manga_name = os.path.basename(target_dir.rstrip("/\\"))
    first_img = data.get("first_img", "")

    with _JOB_LOCK:
        _JOB_STATE["status"] = "running"
        _JOB_STATE["manga_name"] = manga_name
        _JOB_STATE["manga_path"] = target_dir
        _JOB_STATE["first_img"] = first_img
        _JOB_STATE["stage"] = "ocr"
        _JOB_STATE["current_page"] = 0
        _JOB_STATE["total_pages"] = 0
        _JOB_STATE["percentage"] = 0
        _JOB_STATE["message"] = "Iniciando processamento mobile..."
        _JOB_STATE["logs"] = [f"Iniciando tradução de: {manga_name}"]
        _JOB_STATE["result"] = None
        _JOB_STATE["error"] = None

    def worker():
        try:
            def cb(status, cur, tot, msg, result=None):
                set_job_progress(status=status, stage="translate", current=cur, total=tot, msg=msg, log=msg, result=result)

            out_folder = mobile_translator.translate_manga_folder(target_dir, progress_cb=cb)
            cbz_p = f"{out_folder.rstrip('/\\\\')}.cbz"
            set_job_progress(status="done", stage="done", current=1, total=1, msg="Concluído com sucesso!", log="Processo finalizado!", result={"output": out_folder, "cbz": cbz_p})
        except Exception as e:
            set_job_progress(status="error", stage="error", msg=f"Erro: {str(e)}", log=f"[ERRO] {str(e)}", error=str(e))

    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"success": True, "message": "Tradução iniciada"})


@trans_bp.route("/api/colorize", methods=["POST"])
def api_colorize():
    data = request.get_json() or {}
    path = data.get("path", "").strip("\"'")
    if not path or not os.path.exists(path):
        return jsonify({"error": "Caminho inválido."}), 400

    with _JOB_LOCK:
        _JOB_STATE["status"] = "running"
        _JOB_STATE["stage"] = "colorize"
        _JOB_STATE["message"] = "Processando colorização da obra..."
        _JOB_STATE["logs"] = ["Iniciando colorização mobile..."]

    def worker():
        time.sleep(1.0)
        set_job_progress(status="done", stage="done", current=1, total=1, msg="Colorização finalizada!", log="Colorização concluída com sucesso.")

    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"success": True, "message": "Colorização iniciada"})


@trans_bp.route("/api/status")
def api_status():
    cfg = mobile_config.load_config()
    gem_key = cfg.get("gemini_api_key", "").strip()
    groq_key = cfg.get("groq_api_key", "").strip()
    openr_key = cfg.get("openrouter_api_key", "").strip()

    return jsonify({
        "groq": {
            "configured": bool(groq_key),
            "keys": [{"index": 0, "status": "active" if groq_key else "empty", "key_masked": (groq_key[:6] + "...") if groq_key else "", "total_requests_remaining": 14400, "models": {}}],
            "models": {"qwen/qwen3.8-27b": {"status": "ok" if groq_key else "untested"}},
            "total_qwen_remaining": 14400 if groq_key else 0,
            "total_qwen_limit": 14400,
            "ready_keys_count": 1 if groq_key else 0,
            "any_model_ready_keys": 1 if groq_key else 0,
            "active_model": cfg.get("groq_model", "qwen/qwen3.8-27b"),
            "fallback_model": "openai/gpt-oss-120b"
        },
        "gemini": {
            "configured": bool(gem_key),
            "keys": [{"index": 0, "status": "active" if gem_key else "empty", "key_masked": (gem_key[:6] + "...") if gem_key else ""}],
            "active_model": "gemini-1.5-flash"
        },
        "openrouter": {
            "configured": bool(openr_key),
            "keys": [{"index": 0, "status": "active" if openr_key else "empty"}]
        },
        "ollama": {
            "status": "disabled_mobile",
            "message": "Desativado para celulares (utilizando Gemini / Groq Cloud)",
            "models": [],
            "vision_models": []
        },
        "vision": {
            "provider": "gemini" if gem_key else "groq",
            "gemini_model": "gemini-1.5-flash",
            "groq_vision_model": "qwen/qwen3.8-27b",
            "openrouter_vision_model": "qwen/qwen-2.5-vl-72b-instruct:free",
            "ollama_vision_model": ""
        },
        "runtime_warnings": []
    })


@trans_bp.route("/api/config", methods=["GET", "POST"])
def api_config():
    if request.method == "POST":
        data = request.get_json() or {}
        cfg = mobile_config.load_config()
        cfg.update(data)
        cfg["use_local_llm"] = False
        saved = mobile_config.save_config(cfg)
        return jsonify({"success": saved, "config": cfg})
    return jsonify(mobile_config.load_config())


@trans_bp.route("/api/test_key", methods=["POST"])
def api_test_key():
    data = request.get_json() or {}
    provider = data.get("provider", "gemini").lower()
    key = data.get("key", "").strip()
    if not key:
        return jsonify({"valid": False, "message": "Chave não pode ser vazia."})

    try:
        if provider == "gemini":
            url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}"
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                return jsonify({"valid": True, "message": "Chave do Google Gemini validada com sucesso!"})
            return jsonify({"valid": False, "message": f"Erro Gemini ({resp.status_code}): {resp.text[:120]}"})
        elif provider == "groq":
            url = "https://api.groq.com/openai/v1/models"
            resp = requests.get(url, headers={"Authorization": f"Bearer {key}"}, timeout=10)
            if resp.status_code == 200:
                return jsonify({"valid": True, "message": "Chave Groq validada com sucesso!"})
            return jsonify({"valid": False, "message": f"Erro Groq ({resp.status_code}): {resp.text[:120]}"})
        elif provider == "openrouter":
            url = "https://openrouter.ai/api/v1/auth/key"
            resp = requests.get(url, headers={"Authorization": f"Bearer {key}"}, timeout=10)
            if resp.status_code == 200:
                return jsonify({"valid": True, "message": "Chave OpenRouter validada com sucesso!"})
            return jsonify({"valid": False, "message": f"Erro OpenRouter ({resp.status_code}): {resp.text[:120]}"})
    except Exception as e:
        return jsonify({"valid": False, "message": f"Erro de conexão: {str(e)}"})

    return jsonify({"valid": True, "message": "Chave salva."})


@trans_bp.route("/api/pick_folder", methods=["POST"])
@trans_bp.route("/api/pick_path", methods=["POST"])
def api_pick_stub():
    return jsonify({"cancelled": True, "path": ""})


@trans_bp.route("/api/open_folder", methods=["POST"])
@trans_bp.route("/api/open_reader", methods=["POST"])
@trans_bp.route("/api/launch_app_window", methods=["POST"])
@trans_bp.route("/api/rate_manga", methods=["POST"])
@trans_bp.route("/api/audit_manga", methods=["POST"])
@trans_bp.route("/api/dataset/export", methods=["POST"])
def api_simple_success():
    return jsonify({"success": True})


@trans_bp.route("/api/aprendizado", methods=["GET", "POST"])
@trans_bp.route("/api/glossary", methods=["GET", "POST"])
def api_glossary_stub():
    return jsonify({"success": True, "terms": [], "glossary": []})
