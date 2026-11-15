"""
mobile_server.py - Servidor Web Local Flask para o Manga Studio Mobile (Android)
Gerencia endpoints de API, escaneamento de pastas e controle de tradução.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import os
import sys
import threading
from flask import Flask, jsonify, request, send_from_directory

import mobile_config
import mobile_translator

app = Flask(__name__, static_folder="studio", static_url_path="")

_PROGRESS = {
    "status": "idle",
    "current": 0,
    "total": 0,
    "message": "Pronto para traduzir",
    "result": None,
}
_LOCK = threading.Lock()


def update_progress(status, current, total, message, result=None):
    with _LOCK:
        _PROGRESS["status"] = status
        _PROGRESS["current"] = current
        _PROGRESS["total"] = total
        _PROGRESS["message"] = message
        if result:
            _PROGRESS["result"] = result


@app.route("/")
def index():
    return send_from_directory("studio", "index.html")


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "app": "Manga Studio Mobile", "version": "1.0.0"})


@app.route("/api/config", methods=["GET", "POST"])
def config_endpoint():
    if request.method == "POST":
        data = request.get_json() or {}
        cfg = mobile_config.load_config()
        cfg.update(data)
        ok = mobile_config.save_config(cfg)
        return jsonify({"success": ok, "config": cfg})
    return jsonify(mobile_config.load_config())


@app.route("/api/folders")
def list_folders():
    """Escaneia pastas com imagens nos locais comuns do Android."""
    candidates = [
        "/sdcard/MANGAS",
        "/storage/emulated/0/MANGAS",
        "/sdcard/Download",
        "/storage/emulated/0/Download",
    ]
    found = []
    exts = (".jpg", ".jpeg", ".png", ".webp")
    for root in candidates:
        if os.path.isdir(root):
            try:
                for entry in os.listdir(root):
                    full = os.path.join(root, entry)
                    if os.path.isdir(full):
                        has_img = any(f.lower().endswith(exts) for f in os.listdir(full))
                        if has_img:
                            found.append({"name": entry, "path": full})
            except Exception:
                pass
    return jsonify({"folders": found})


@app.route("/api/translate", methods=["POST"])
def start_translate():
    with _LOCK:
        if _PROGRESS["status"] in ("translating", "running"):
            return jsonify({"success": False, "error": "Tradução já em andamento"}), 409

    data = request.get_json() or {}
    input_path = data.get("path")
    if not input_path or not os.path.isdir(input_path):
        return jsonify({"success": False, "error": "Pasta inválida ou não encontrada"}), 400

    def run_worker():
        try:
            update_progress("translating", 0, 1, "Iniciando processamento mobile...")
            out_folder = mobile_translator.translate_manga_folder(
                input_path, progress_cb=update_progress
            )
            update_progress("done", 1, 1, "Concluído!", result={"output": out_folder})
        except Exception as e:
            update_progress("error", 0, 0, f"Erro: {str(e)}")

    thread = threading.Thread(target=run_worker, daemon=True)
    thread.start()
    return jsonify({"success": True, "message": "Tradução iniciada"})


@app.route("/api/status")
def status_endpoint():
    with _LOCK:
        return jsonify(_PROGRESS)


def start_server(port=5000):
    """Inicia o servidor Flask localmente em 127.0.0.1."""
    print(f"[+] Iniciando Manga Studio Mobile em http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    start_server(5000)
