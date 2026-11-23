"""
mobile_security.py - Token de acesso do servidor local e restrição de caminhos
Impede que outros apps do celular leiam chaves de API ou apaguem arquivos via 127.0.0.1.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import hmac
import os
import secrets
from flask import jsonify, request

import mobile_config

COOKIE_NAME = "ms_token"
PUBLIC_PREFIXES = ("/api/health", "/static/", "/favicon.ico", "/manifest.json", "/sw.js")
_STATE = {"token": ""}


def set_token(token=None):
    """Define o token da sessão (gerado pelo app Android). Sem token, gera um aleatório."""
    _STATE["token"] = str(token or secrets.token_urlsafe(32))
    return _STATE["token"]


def get_token():
    return _STATE["token"]


def _matches(candidate):
    tok = get_token()
    if not tok or not candidate:
        return False
    return hmac.compare_digest(str(candidate).encode("utf-8"), tok.encode("utf-8"))


def install(app):
    """Exige o token (query ?token= ou cookie) em todas as rotas, exceto as públicas."""

    @app.before_request
    def _require_token():
        if not get_token():
            return None  # Token não configurado (ex.: testes unitários)
        if request.path.startswith(PUBLIC_PREFIXES):
            return None
        if _matches(request.args.get("token")) or _matches(request.cookies.get(COOKIE_NAME)):
            return None
        return jsonify({"error": "Acesso negado: token do Manga Studio ausente ou inválido."}), 403

    @app.after_request
    def _persist_cookie(resp):
        if _matches(request.args.get("token")):
            resp.set_cookie(COOKIE_NAME, get_token(), httponly=True, samesite="Strict")
        return resp


def allowed_roots(include_raw=False):
    """Pastas onde o app pode apagar/exportar: saída traduzida, uploads e extraídos (+ brutos se pedido)."""
    cfg = mobile_config.load_config()
    base = mobile_config.get_base_dir()
    roots = [
        cfg.get("output_dir"),
        cfg.get("translated_mangas_dir"),
        os.path.join(base, "uploads"),
        os.path.join(base, "extracted"),
    ]
    if include_raw:
        roots += [cfg.get("input_dir"), cfg.get("raw_mangas_dir")]
    out = []
    for r in roots:
        if r:
            rp = os.path.realpath(r)
            if rp not in out:
                out.append(rp)
    return out


def is_within(path, roots):
    """True se o caminho (com symlinks resolvidos) estiver ESTRITAMENTE dentro de uma das raízes."""
    if not path:
        return False
    rp = os.path.realpath(path)
    for r in roots:
        base = r.rstrip(os.sep) + os.sep
        if rp != r and rp.startswith(base):
            return True
    return False
