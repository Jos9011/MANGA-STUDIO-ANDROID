"""
mobile_routes_export.py - Download de CBZ e de pastas traduzidas (ZIP) com caminhos restritos
Só exporta arquivos de dentro das pastas de mangás do app (nunca arquivos arbitrários).
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import os
import zipfile
from flask import Blueprint, jsonify, request, send_file

import mobile_config
import mobile_security

export_bp = Blueprint("export_bp", __name__)
IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp")


def _requested_path():
    return request.args.get("path", "").strip("\"'")


@export_bp.route("/api/download_cbz")
def api_download_cbz():
    """Envia o .cbz traduzido para download."""
    path = _requested_path()
    if not path or not os.path.isfile(path):
        return jsonify({"error": "Arquivo não encontrado"}), 404
    if not path.lower().endswith(".cbz") or not mobile_security.is_within(path, mobile_security.allowed_roots()):
        return jsonify({"error": "Download bloqueado: arquivo fora das pastas de mangás."}), 403
    return send_file(path, as_attachment=True, download_name=os.path.basename(path),
                     mimetype="application/octet-stream")


@export_bp.route("/api/download_folder")
def api_download_folder():
    """Compacta as páginas de uma obra traduzida em ZIP e envia para download."""
    path = _requested_path().rstrip("/\\")
    if not path or not os.path.isdir(path):
        return jsonify({"error": "Pasta não encontrada"}), 404
    if not mobile_security.is_within(path, mobile_security.allowed_roots()):
        return jsonify({"error": "Download bloqueado: pasta fora das pastas de mangás."}), 403

    name = os.path.basename(path) or "manga"
    export_dir = os.path.join(mobile_config.get_base_dir(), "exports")
    os.makedirs(export_dir, exist_ok=True)
    zip_path = os.path.join(export_dir, f"{name}.zip")
    files = sorted(f for f in os.listdir(path) if f.lower().endswith(IMG_EXTS) or f == "leitor.html")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(os.path.join(path, f), arcname=f)
    return send_file(zip_path, as_attachment=True, download_name=f"{name}.zip",
                     mimetype="application/octet-stream")
