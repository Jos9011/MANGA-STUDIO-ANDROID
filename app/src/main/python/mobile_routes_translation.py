"""
mobile_routes_translation.py - Endpoints de Tradução por IA, Colorização e Configurações
Gerencia o ciclo de vida dos jobs de IA em background e validação de chaves.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import os
import threading
import requests
from flask import Blueprint, jsonify, request

import mobile_colorizer
import mobile_config
import mobile_drive_helper
import mobile_job_control
import mobile_quota_checker
import mobile_translator
import mobile_version

trans_bp = Blueprint("trans_bp", __name__)
_JOB_CTRL = mobile_job_control.JobController()

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


def _resolve_target(path):
    """Pasta do capítulo (ZIP/CBZ é extraído antes) ou None."""
    if os.path.isfile(path) and path.lower().endswith((".zip", ".cbz")):
        return mobile_drive_helper.extract_manga_archive(path)
    return path


def _start_job(target_dir, first_img, work, stage, start_msg):
    """Inicia uma tarefa em segundo plano (tradução ou colorização) com pausar/parar."""
    manga_name = os.path.basename(target_dir.rstrip("/\\"))
    with _JOB_LOCK:
        _JOB_CTRL.reset()
        _JOB_STATE.update({"status": "running", "manga_name": manga_name, "manga_path": target_dir,
                           "first_img": first_img, "stage": stage, "current_page": 0, "total_pages": 0,
                           "percentage": 0, "message": start_msg, "logs": [f"{start_msg}: {manga_name}"],
                           "result": None, "error": None})

    def worker():
        try:
            summary, final_msg = work()
            set_job_progress(status="done", stage="done", current=1, total=1, msg=final_msg, log=final_msg, result=summary)
        except mobile_job_control.JobCancelledError:
            set_job_progress(status="cancelled", stage="cancelled", msg="Tarefa interrompida pelo usuário.", log="Tarefa encerrada com segurança.")
        except Exception as e:
            set_job_progress(status="error", stage="error", msg=f"Erro: {str(e)}", log=f"[ERRO] {str(e)}", error=str(e))
        finally:
            mobile_colorizer.release()

    threading.Thread(target=worker, daemon=True).start()


def _colorize_step(folder, output_dir=None):
    """Colore as páginas com o progresso na tela; devolve o resumo e a frase final."""
    def cb(cur, tot, msg):
        _JOB_CTRL.checkpoint()
        set_job_progress(status="running", stage="colorize", current=cur, total=tot, msg=msg, log=msg)

    summary = mobile_colorizer.colorize_folder(folder, output_dir=output_dir, progress_cb=cb, checkpoint=_JOB_CTRL.checkpoint)
    msg = f"Colorização concluída: {summary['colorized']} de {summary['total']} páginas em {summary['seconds']:.0f} s."
    if summary["errors"]:
        msg += f" {len(summary['errors'])} página(s) com erro: {summary['errors'][0]}"
    return summary, msg


def _busy():
    with _JOB_LOCK:
        return _JOB_STATE["status"] in ("running", "paused")


@trans_bp.route("/api/start", methods=["POST"])
def api_start():
    if _busy():
        return jsonify({"error": "Já existe uma tradução em andamento ou pausada!"}), 409
    data = request.get_json() or {}
    path = data.get("path", "").strip("\"'")
    if not path or not os.path.exists(path):
        return jsonify({"error": "Caminho inválido ou não encontrado."}), 400
    target_dir = _resolve_target(path)
    if not target_dir:
        return jsonify({"error": "Falha ao extrair páginas do arquivo."}), 400
    if data.get("colorize_only"):
        return api_colorize()
    want_color = bool(data.get("colorize"))

    def work():
        def cb(status, cur, tot, msg, result=None):
            _JOB_CTRL.checkpoint()
            eff_st = "running" if status == "translating" else status
            set_job_progress(status=eff_st, stage="translate", current=cur, total=tot, msg=msg, log=msg, result=result)

        summary = mobile_translator.translate_manga_folder(target_dir, progress_cb=cb)
        final_msg = mobile_translator.summary_message(summary)
        if want_color and summary.get("output") and os.path.isdir(summary["output"]):
            color, color_msg = _colorize_step(summary["output"], output_dir=summary["output"])
            summary["colorize"] = color
            final_msg = f"{final_msg} {color_msg}"
        return summary, final_msg

    _start_job(target_dir, data.get("first_img", ""), work, "ocr", "Iniciando tradução")
    return jsonify({"success": True, "message": "Tradução iniciada"})


@trans_bp.route("/api/colorize", methods=["POST"])
def api_colorize():
    """Só colorir: as páginas coloridas vão para a pasta de traduzidos com " [COLORIDO]" no nome."""
    if _busy():
        return jsonify({"error": "Já existe uma tarefa em andamento ou pausada!"}), 409
    data = request.get_json() or {}
    path = data.get("path", "").strip("\"'")
    target_dir = _resolve_target(path) if path and os.path.exists(path) else None
    if not target_dir:
        return jsonify({"error": "Caminho inválido ou não encontrado."}), 400
    _start_job(target_dir, data.get("first_img", ""), lambda: _colorize_step(target_dir), "colorize", "Iniciando colorização")
    return jsonify({"success": True, "message": "Colorização iniciada"})


@trans_bp.route("/api/job/pause", methods=["POST"])
def api_job_pause():
    with _JOB_LOCK:
        if _JOB_STATE["status"] != "running":
            return jsonify({"success": False, "error": "Nenhuma tradução ativa para pausar."}), 400
        _JOB_CTRL.pause()
        _JOB_STATE["status"] = "paused"
        _JOB_STATE["message"] = "⏸️ Tradução pausada pelo usuário."
        _JOB_STATE["logs"].append("⏸️ Pausa solicitada...")
    return jsonify({"success": True, "status": "paused"})


@trans_bp.route("/api/job/resume", methods=["POST"])
def api_job_resume():
    with _JOB_LOCK:
        if _JOB_STATE["status"] != "paused":
            return jsonify({"success": False, "error": "A tradução não está pausada."}), 400
        _JOB_CTRL.resume()
        _JOB_STATE["status"] = "running"
        _JOB_STATE["message"] = "▶️ Tradução retomada..."
        _JOB_STATE["logs"].append("▶️ Tradução retomada.")
    return jsonify({"success": True, "status": "running"})


@trans_bp.route("/api/job/stop", methods=["POST"])
def api_job_stop():
    with _JOB_LOCK:
        if _JOB_STATE["status"] not in ("running", "paused"):
            return jsonify({"success": False, "error": "Nenhuma tradução ativa para parar."}), 400
        _JOB_CTRL.stop()
        _JOB_STATE["message"] = "⏹️ Parando tradução com segurança..."
        _JOB_STATE["logs"].append("⏹️ Cancelamento solicitado...")
    return jsonify({"success": True, "status": "stopping"})


@trans_bp.route("/api/status")
def api_status():
    return jsonify(mobile_quota_checker.build_live_status())


@trans_bp.route("/api/config", methods=["GET", "POST"])
def api_config():
    if request.method == "POST":
        data = request.get_json() or {}
        cfg = mobile_config.load_config()
        cfg.update(data)
        cfg["use_local_llm"] = False
        saved = mobile_config.save_config(cfg)
        cfg["app_version"] = mobile_version.APP_VERSION
        cfg["app_version_name"] = mobile_version.APP_VERSION_NAME
        return jsonify({"success": saved, "config": cfg})
    cfg = mobile_config.load_config()
    cfg["app_version"] = mobile_version.APP_VERSION
    cfg["app_version_name"] = mobile_version.APP_VERSION_NAME
    return jsonify(cfg)


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
