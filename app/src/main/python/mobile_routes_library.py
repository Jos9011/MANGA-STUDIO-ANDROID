"""
mobile_routes_library.py - Endpoints de Biblioteca, Google Drive e Visualizador Web
Gerencia listagem de mangás, miniaturas, leitura e uploads.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import os
import re
import shutil
import zipfile
from flask import Blueprint, jsonify, redirect, request, send_file, send_from_directory

import mobile_config
import mobile_drive_helper
import mobile_typesetter

library_bp = Blueprint("library_bp", __name__)
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "studio", "static")


@library_bp.route("/api/drive_folders")
def api_drive_folders():
    """Lista pastas e arquivos de mangás disponíveis no Google Drive e Armazenamento."""
    roots = mobile_drive_helper.find_drive_roots()
    folders = []
    seen = set()
    search_dirs = []

    for r in roots:
        if os.path.exists(r):
            manga_sub = os.path.join(r, "MANGAS")
            if os.path.exists(manga_sub):
                search_dirs.append(manga_sub)
            search_dirs.append(r)

    img_exts = (".jpg", ".jpeg", ".png", ".webp")
    for base in search_dirs:
        try:
            for item in sorted(os.listdir(base)):
                p = os.path.abspath(os.path.join(base, item))
                if p in seen or item.startswith(".") or item == "_ocr" or item.endswith("[PT-BR]"):
                    continue

                if os.path.isdir(p):
                    imgs = [f for f in os.listdir(p) if f.lower().endswith(img_exts)]
                    if imgs:
                        seen.add(p)
                        folders.append({
                            "name": item,
                            "path": p,
                            "pages": len(imgs),
                            "is_archive": False
                        })
                elif os.path.isfile(p) and item.lower().endswith((".zip", ".cbz")):
                    try:
                        with zipfile.ZipFile(p, "r") as z:
                            zip_imgs = [
                                inf.filename for inf in z.infolist()
                                if not inf.is_dir() and inf.filename.lower().endswith(img_exts)
                            ]
                            if zip_imgs:
                                seen.add(p)
                                folders.append({
                                    "name": f"📦 {item}",
                                    "path": p,
                                    "pages": len(zip_imgs),
                                    "is_archive": True
                                })
                    except Exception:
                        pass
        except Exception:
            pass

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
    """Retorna miniatura da capa gerada sob demanda com fallback seguro."""
    img_path = request.args.get("path", "").strip("\"'")
    if img_path:
        thumb_p = mobile_drive_helper.generate_thumbnail(img_path)
        if thumb_p and os.path.exists(thumb_p):
            return send_file(thumb_p, mimetype="image/jpeg")

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
                    "detected_label": "IA Nuvem (Gemini / Groq)",
                    "detected_engine": "cloud"
                })
        except Exception as e:
            return jsonify({"valid": False, "error": f"Erro ao ler arquivo: {e}"})

    if os.path.isdir(path):
        imgs = [f for f in os.listdir(path) if f.lower().endswith(img_exts)]
        if not imgs:
            return jsonify({"valid": False, "error": "Nenhuma imagem encontrada na pasta."})
        imgs.sort(key=mobile_drive_helper.natural_sort_key)
        return jsonify({
            "valid": True,
            "name": os.path.basename(path),
            "path": path,
            "pages": len(imgs),
            "first_img": os.path.join(path, imgs[0]),
            "detected_label": "IA Nuvem (Gemini / Groq)",
            "detected_engine": "cloud"
        })

    return jsonify({"valid": False, "error": "Formato não suportado."})


@library_bp.route("/api/upload", methods=["POST"])
def api_upload():
    """Recebe arquivos de mangá enviados via seletor nativo do Android."""
    upload_base = os.path.join(mobile_config.get_base_dir(), "uploads")
    os.makedirs(upload_base, exist_ok=True)

    if "zip_file" in request.files:
        file = request.files["zip_file"]
        fname = file.filename or "manga.zip"
        clean_name = os.path.splitext(fname)[0]
        clean_name = re.sub(r'[\\/*?:"<>|]', "", clean_name).strip() or "Manga_Upload"
        temp_arc = os.path.join(upload_base, f"temp_{fname}")
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
