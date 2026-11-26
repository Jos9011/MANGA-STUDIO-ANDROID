"""
mobile_server.py - Servidor Web Principal Flask do Manga Studio Mobile (Android)
Serve o dashboard visual completo do Manga Studio e orquestra blueprints e APIs.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import os
from flask import Flask, jsonify, render_template, send_from_directory

import mobile_security
from mobile_routes_export import export_bp
from mobile_routes_gdrive import gdrive_bp
from mobile_routes_library import library_bp
from mobile_routes_translation import trans_bp

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "studio", "templates")
STATIC_DIR = os.path.join(BASE_DIR, "studio", "static")

app = Flask(
    __name__,
    template_folder=TEMPLATES_DIR,
    static_folder=STATIC_DIR,
    static_url_path="/static"
)
mobile_security.install(app)

APP_VERSION = "0.8.1-beta"
APP_VERSION_NAME = "v0.8.1 Beta"


@app.context_processor
def inject_version():
    """Injeta as variáveis oficiais da versão v0.8.1 Beta em todos os templates Jinja."""
    return {
        "app_version": APP_VERSION_NAME,
        "app_version_code": APP_VERSION,
    }


# Registra os módulos de rotas
app.register_blueprint(library_bp)
app.register_blueprint(trans_bp)
app.register_blueprint(export_bp)
app.register_blueprint(gdrive_bp)


@app.route("/")
def index():
    """Renderiza a interface web completa do Manga Studio."""
    return render_template("index.html")


@app.route("/manifest.json")
def manifest():
    return send_from_directory(STATIC_DIR, "manifest.json")


@app.route("/sw.js")
def service_worker():
    return send_from_directory(STATIC_DIR, "sw.js")


@app.route("/favicon.ico")
def favicon():
    return send_from_directory(STATIC_DIR, "favicon.ico")


@app.route("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "app": "Manga Studio Mobile",
        "version": APP_VERSION,
        "version_name": APP_VERSION_NAME,
    })


@app.route("/api/version")
def api_version():
    return jsonify({
        "version": APP_VERSION,
        "version_name": APP_VERSION_NAME,
        "release": f"Manga Studio {APP_VERSION_NAME}",
        "platform": "Android",
    })


def start_server(port=5000, token=None):
    """Inicia o servidor Flask local exigindo o token de sessão gerado pelo app Android."""
    tok = mobile_security.set_token(token)
    print(f"[+] Servidor Manga Studio Mobile online em http://127.0.0.1:{port}")
    if not token:
        print(f"[+] Acesse: http://127.0.0.1:{port}/?token={tok}")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    start_server(5000)
