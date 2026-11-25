"""
mobile_routes_gdrive.py - Rotas do Google Drive na Biblioteca do app
GET  /api/gdrive/status          -> {"connected": bool}
GET  /api/gdrive/list            -> {"items": [...]}  (401 {"error": "auth"} se precisar logar)
POST /api/gdrive/download        -> inicia download {"id", "name", "kind"}
GET  /api/gdrive/download_status -> progresso do download
POST /api/gdrive/disconnect      -> esquece o token
Todas passam pelo token de sessão do app (mobile_security).
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

from flask import Blueprint, jsonify, request

import mobile_config
import mobile_drive_helper
import mobile_gdrive

gdrive_bp = Blueprint("gdrive_bp", __name__)


def _base_dir():
    cfg = mobile_config.load_config()
    return cfg.get("input_dir") or cfg.get("raw_mangas_dir") or "/sdcard/MANGAS"


def _root_name():
    return str(mobile_config.load_config().get("gdrive_root_folder") or "MANGAS").strip() or "MANGAS"


@gdrive_bp.route("/api/gdrive/status")
def gdrive_status():
    return jsonify({"connected": mobile_gdrive.is_connected(), "root": _root_name()})


@gdrive_bp.route("/api/gdrive/list")
def gdrive_list():
    try:
        items = mobile_gdrive.list_mangas(_base_dir(), _root_name())
        return jsonify({"items": items, "root": _root_name()})
    except mobile_gdrive.DriveAuthError as e:
        return jsonify({"error": "auth", "message": str(e)}), 401
    except mobile_gdrive.DriveNotFound as e:
        return jsonify({"error": "not_found", "message": str(e)}), 404
    except Exception as e:
        return jsonify({"error": "drive", "message": str(e)}), 502


@gdrive_bp.route("/api/gdrive/download", methods=["POST"])
def gdrive_download():
    data = request.get_json() or {}
    item = {"id": str(data.get("id") or ""), "name": str(data.get("name") or ""), "kind": data.get("kind")}
    try:
        started = mobile_gdrive.start_download(item, _base_dir(), mobile_drive_helper.extract_manga_archive)
    except mobile_gdrive.DriveAuthError as e:
        return jsonify({"error": "auth", "message": str(e)}), 401
    except ValueError as e:
        return jsonify({"error": "invalid", "message": str(e)}), 400
    if not started:
        return jsonify({"error": "busy", "message": "Já existe um download do Drive em andamento."}), 409
    return jsonify({"started": True})


@gdrive_bp.route("/api/gdrive/download_status")
def gdrive_download_status():
    return jsonify(mobile_gdrive.job_status())


@gdrive_bp.route("/api/gdrive/disconnect", methods=["POST"])
def gdrive_disconnect():
    mobile_gdrive.clear_token()
    return jsonify({"connected": False})
