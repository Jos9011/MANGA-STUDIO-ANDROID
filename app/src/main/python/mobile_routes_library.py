"""
mobile_routes_library.py - Endpoints de Biblioteca, Google Drive e Visualizador Web
Gerencia listagem de mangás, miniaturas, leitura e uploads.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import os
import re
import shutil
import zipfile
from flask import Blueprint, Response, jsonify, redirect, request, send_file, send_from_directory

import mobile_config
import mobile_drive_helper
import mobile_thumb_helper
import mobile_typesetter

library_bp = Blueprint("library_bp", __name__)
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "studio", "static")


@library_bp.route("/api/drive_folders")
def api_drive_folders():
    """Lista pastas e arquivos ZIP/CBZ do armazenamento Android e Google Drive."""
    roots = mobile_drive_helper.find_drive_roots()
    folders = []
    seen = set()
    search_dirs, seen_dirs = [], set()

    for r in roots:
        if not os.path.exists(r):
            continue
        try:
            for sub in sorted(os.listdir(r)):
                sp = os.path.join(r, sub)
                if os.path.isdir(sp) and "manga" in sub.lower() and not sub.startswith("."):
                    rk = mobile_drive_helper.real_path_key(sp)
                    if rk not in seen_dirs:
                        seen_dirs.add(rk)
                        search_dirs.append(sp)
        except Exception:
            pass
        rk_r = mobile_drive_helper.real_path_key(r)
        if rk_r not in seen_dirs:
            seen_dirs.add(rk_r)
            search_dirs.append(r)

    for base in search_dirs:
        for e in mobile_drive_helper.scan_directory(base, seen):
            folders.append({
                "name": f"📦 {e['name']}" if e.get("is_archive") else e["name"],
                "path": e["path"],
                "pages": e["pages"],
                "is_archive": e.get("is_archive", False),
            })

    return jsonify({"available": True, "folders": folders})


@library_bp.route("/api/library")
def api_library():
    """Retorna lista de mangás traduzidos e prontos para traduzir."""
    cfg = mobile_config.load_config()
    raw_dir = cfg.get("input_dir", "/sdcard/MANGAS")
    trans_dir = cfg.get("output_dir", "/sdcard/MANGAS [PT-BR]")
    upload_dir = os.path.join(mobile_config.get_base_dir(), "uploads")

    translated = []
    raw = []
    seen = set()

    for sf in [trans_dir]:
        for e in mobile_drive_helper.scan_directory(sf, seen):
            translated.append(e)

    for rf in [raw_dir, upload_dir] + mobile_drive_helper.find_drive_roots():
        for e in mobile_drive_helper.scan_directory(rf, seen):
            if "[PT-BR]" in e["name"] or e.get("has_reader"):
                if e not in translated:
                    translated.append(e)
            else:
                raw.append(e)

    translated = mobile_drive_helper.deduplicate_entries(translated)
    raw = mobile_drive_helper.deduplicate_entries(raw)
    translated.sort(key=lambda x: x["mtime"], reverse=True)
    raw.sort(key=lambda x: x["mtime"], reverse=True)
    return jsonify({
        "translated": translated,
        "raw": raw,
        "translated_count": len(translated),
        "available_count": len(raw),
        "drive_connected": True
    })


@library_bp.route("/api/thumb")
def api_thumb():
    """Retorna miniatura da capa com fallback nativo em bytes para Chromium WebView."""
    img_path = request.args.get("path", "").strip("\"'")
    if img_path:
        kind, payload, mime = mobile_thumb_helper.get_thumbnail_or_raw(img_path)
        if kind == "file" and payload and os.path.exists(payload):
            return send_file(payload, mimetype=mime or "image/jpeg")
        if kind == "bytes" and payload:
            return Response(payload, mimetype=mime or "image/jpeg")

    logo_p = os.path.join(STATIC_DIR, "logo.png")
    if os.path.exists(logo_p):
        return send_file(logo_p, mimetype="image/png")
    return "", 404


@library_bp.route("/api/reader")
def api_reader():
    """Redireciona para o leitor web com hash da obra."""
    path = request.args.get("path", "").strip("\"'")
    if not path or not os.path.exists(path):
        return "Caminho não encontrado", 404
    h = mobile_drive_helper.get_manga_hash(path)
    return redirect(f"/read/{h}/")


@library_bp.route("/read/<manga_id>/")
@library_bp.route("/read/<manga_id>/<path:filename>")
def serve_manga_reader(manga_id, filename="leitor.html"):
    """Serve páginas do leitor web diretamente na WebView."""
    folder = mobile_drive_helper.MANGA_PATH_CACHE.get(manga_id)
    if not folder or not os.path.exists(folder):
        return "Obra não encontrada no leitor.", 404

    leitor_p = os.path.join(folder, "leitor.html")
    if filename == "leitor.html" and not os.path.exists(leitor_p):
        mobile_typesetter.make_offline_reader(folder, os.path.basename(folder))

    return send_from_directory(folder, filename)


@library_bp.route("/api/drive/extract_all", methods=["POST"])
def api_drive_extract_all():
    """Extrai todos os pacotes ZIP e CBZ encontrados no Google Drive."""
    count = mobile_drive_helper.extract_all_drive_archives()
    return jsonify({
        "success": True,
        "count": count,
        "message": f"{count} obra(s) descompactada(s) com sucesso!"
    })


@library_bp.route("/api/inspect_folder", methods=["POST"])
def api_inspect_folder():
    """Valida a pasta ou arquivo selecionado e retorna metadados."""
    data = request.get_json() or {}
    path = data.get("path", "").strip("\"'")
    if not path or not os.path.exists(path):
        return jsonify({"valid": False, "error": "Caminho inexistente"}), 404

    img_exts = (".jpg", ".jpeg", ".png", ".webp")
    if os.path.isfile(path) and path.lower().endswith((".zip", ".cbz")):
        try:
            with zipfile.ZipFile(path, "r") as z:
                zip_imgs = [
                    f.filename for f in z.infolist()
                    if not f.is_dir() and f.filename.lower().endswith(img_exts)
                ]
                if not zip_imgs:
                    return jsonify({"valid": False, "error": "Arquivo não contém imagens válidas."})
                zip_imgs.sort(key=mobile_drive_helper.natural_sort_key)
                return jsonify({
                    "valid": True,
                    "name": os.path.splitext(os.path.basename(path))[0],
                    "path": path,
                    "pages": len(zip_imgs),
                    "first_img": f"{path}::{zip_imgs[0]}",
                    "detected_label": "IA Nuvem (Groq / Gemini / OpenRouter)",
                    "detected_engine": "auto"
                })
        except Exception as e:
            return jsonify({"valid": False, "error": f"Erro ao ler arquivo: {e}"})

    if os.path.isdir(path):
        imgs = [f for f in os.listdir(path) if f.lower().endswith(img_exts)]
        first_img_p = None
        if imgs:
            imgs.sort(key=mobile_drive_helper.natural_sort_key)
            first_img_p = os.path.join(path, imgs[0])
        else:
            for d in sorted(os.listdir(path), key=mobile_drive_helper.natural_sort_key):
                sub = os.path.join(path, d)
                if os.path.isdir(sub) and not d.startswith("."):
                    s_imgs = [f for f in os.listdir(sub) if f.lower().endswith(img_exts)]
                    if s_imgs:
                        s_imgs.sort(key=mobile_drive_helper.natural_sort_key)
                        imgs = s_imgs
                        first_img_p = os.path.join(sub, s_imgs[0])
                        break
        if not imgs:
            return jsonify({"valid": False, "error": "Nenhuma imagem encontrada na pasta."})
        return jsonify({
            "valid": True,
            "name": os.path.basename(path),
            "path": path,
            "pages": len(imgs),
            "first_img": first_img_p,
            "detected_label": "IA Nuvem (Groq / Gemini / OpenRouter)",
            "detected_engine": "auto"
        })

    return jsonify({"valid": False, "error": "Formato não suportado."})


@library_bp.route("/api/upload", methods=["POST"])
def api_upload():
    """Recebe arquivos de mangá enviados via seletor nativo/Google Drive do Android."""
    upload_base = os.path.join(mobile_config.get_base_dir(), "uploads")
    os.makedirs(upload_base, exist_ok=True)

    if "zip_file" in request.files:
        file = request.files["zip_file"]
        raw_name = os.path.basename(str(file.filename or "manga.zip").replace("\\", "/"))
        clean_name = os.path.splitext(raw_name)[0]
        clean_name = re.sub(r'[\\/*?:"<>|:]', "_", clean_name).strip() or "Manga_Upload"
        temp_arc = os.path.join(upload_base, f"temp_{clean_name}.zip")
        file.save(temp_arc)
        try:
            target_dir = mobile_drive_helper.extract_manga_archive(temp_arc)
            if target_dir:
                return jsonify({"success": True, "path": target_dir, "name": clean_name})
            return jsonify({"success": False, "error": "Nenhuma página válida extraída"}), 400
        finally:
            if os.path.exists(temp_arc):
                os.remove(temp_arc)

    files = request.files.getlist("files[]")
    folder_name = request.form.get("folder_name", "Manga_Upload").strip() or "Manga_Upload"
    folder_name = re.sub(r'[\\/*?:"<>|]', "", folder_name).strip() or "Manga_Upload"
    target_dir = os.path.join(upload_base, folder_name)
    os.makedirs(target_dir, exist_ok=True)

    for f in files:
        if f.filename.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            f.save(os.path.join(target_dir, os.path.basename(f.filename)))

    return jsonify({"success": True, "path": target_dir, "name": folder_name})


@library_bp.route("/api/download_cbz")
def api_download_cbz():
    """Envia arquivo CBZ para download ou compartilhamento."""
    path = request.args.get("path", "").strip("\"'")
    if not path or not os.path.exists(path):
        return jsonify({"error": "Arquivo não encontrado"}), 404
    return send_file(path, as_attachment=True, download_name=os.path.basename(path))


@library_bp.route("/api/delete_manga", methods=["POST"])
def api_delete_manga():
    """Remove uma obra traduzida da biblioteca."""
    data = request.get_json() or {}
    path = data.get("path", "").strip("\"'")
    if not path or not os.path.exists(path):
        return jsonify({"success": False, "error": "Caminho não encontrado"}), 404

    try:
        if os.path.isdir(path):
            shutil.rmtree(path)
            cbz_candidate = path.rstrip("/\\") + ".cbz"
            if os.path.exists(cbz_candidate):
                os.remove(cbz_candidate)
        elif os.path.isfile(path):
            os.remove(path)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
