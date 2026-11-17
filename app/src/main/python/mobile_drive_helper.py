"""
mobile_drive_helper.py - Utilitários de Armazenamento e Google Drive para Android
Localiza caminhos de armazenamento, extrai arquivos ZIP/CBZ e gera thumbnails.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import hashlib
import io
import os
import re
import zipfile
from PIL import Image

import mobile_config

MANGA_PATH_CACHE = {}


def real_path_key(path):
    """Retorna chave canônica resolvendo symlinks (/sdcard -> /storage/emulated/0)."""
    if not path:
        return ""
    try:
        return os.path.normcase(os.path.realpath(path))
    except Exception:
        return os.path.normcase(os.path.abspath(path))


def get_manga_hash(path):
    """Gera um hash curto para identificar a pasta na URL do leitor web."""
    clean = os.path.abspath(path).replace("\\", "/")
    h = hashlib.md5(real_path_key(clean).encode("utf-8")).hexdigest()[:12]
    MANGA_PATH_CACHE[h] = clean
    return h


def find_drive_roots():
    """Retorna locais únicos do Android/Drive sem duplicar symlinks."""
    candidates = [
        "/storage/emulated/0/Download",
        "/storage/emulated/0/MANGAS",
        "/storage/emulated/0/Google Drive",
        "/storage/emulated/0/Documents",
        "/sdcard/Download",
        "/sdcard/MANGAS",
        "/sdcard/Google Drive",
        "/sdcard/Documents",
        os.path.expanduser("~/storage/shared/Download"),
        os.path.expanduser("~/storage/shared/MANGAS"),
        "/content/drive/MyDrive",
    ]
    cfg = mobile_config.load_config()
    for extra in (cfg.get("raw_mangas_dir"), cfg.get("input_dir"), cfg.get("drive_folder")):
        if extra and extra not in candidates:
            candidates.append(extra)

    roots, seen_real = [], set()
    for c in candidates:
        if c and os.path.exists(c):
            rk = real_path_key(c)
            if rk not in seen_real:
                seen_real.add(rk)
                roots.append(os.path.abspath(c))
    return roots if roots else ["/storage/emulated/0/Download", "/storage/emulated/0/MANGAS"]


def is_drive_path(p):
    """Verifica se o caminho informado está em armazenamento externo ou Drive."""
    if not p:
        return False
    clean = os.path.abspath(p).replace("\\", "/").lower()
    return any(k in clean for k in ("drive", "emulated", "sdcard", "download"))


def natural_sort_key(s):
    """Ordenação natural de nomes de arquivos com números (ex: 1, 2, 10)."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def extract_manga_archive(archive_path, target_dir=None):
    """Extrai arquivo ZIP ou CBZ para uma pasta temporária organizada."""
    if not os.path.exists(archive_path):
        return None

    clean_name = os.path.splitext(os.path.basename(archive_path))[0]
    clean_name = re.sub(r'[\\/*?:"<>|]', "", clean_name).strip() or "Manga_Extracted"

    if not target_dir:
        base_up = os.path.join(mobile_config.get_base_dir(), "extracted")
        target_dir = os.path.join(base_up, clean_name)

    os.makedirs(target_dir, exist_ok=True)
    img_exts = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
    with zipfile.ZipFile(archive_path, "r") as z:
        for member in z.infolist():
            if member.is_dir():
                continue
            fname = os.path.basename(member.filename)
            if not fname or fname.startswith(".") or fname.startswith("__MACOSX"):
                continue
            if any(fname.lower().endswith(ext) for ext in img_exts):
                dest_file = os.path.join(target_dir, fname)
                with z.open(member) as source, open(dest_file, "wb") as target:
                    target.write(source.read())

    extracted_imgs = [f for f in os.listdir(target_dir) if any(f.lower().endswith(ext) for ext in img_exts)]
    return target_dir if extracted_imgs else None


def extract_all_drive_archives():
    """Varre pastas do Google Drive e extrai todos os ZIPs e CBZs encontrados."""
    roots = find_drive_roots()
    cfg = mobile_config.load_config()
    target_base = cfg.get("input_dir", "/sdcard/MANGAS")
    os.makedirs(target_base, exist_ok=True)
    count = 0
    for r in roots:
        if not os.path.exists(r):
            continue
        try:
            for item in os.listdir(r):
                if item.lower().endswith((".zip", ".cbz")):
                    arc_p = os.path.join(r, item)
                    clean_name = os.path.splitext(item)[0]
                    clean_dir = os.path.join(target_base, clean_name)
                    if not os.path.exists(clean_dir):
                        if extract_manga_archive(arc_p, clean_dir):
                            count += 1
        except Exception:
            pass
    return count


def _safe_convert_and_save(im, dest):
    """Converte imagem tratando transparência e salva miniatura JPG com qualidade."""
    if im.mode in ("RGBA", "LA", "P"):
        im_rgba = im.convert("RGBA")
        bg = Image.new("RGB", im_rgba.size, (24, 24, 24))
        bg.paste(im_rgba, mask=im_rgba.split()[-1])
        im_final = bg
    else:
        im_final = im.convert("RGB")
    im_final.thumbnail((320, 460), Image.Resampling.LANCZOS)
    im_final.save(dest, "JPEG", quality=85)


def generate_thumbnail(img_path):
    """Gera miniatura compacta (320x460) com Pillow a partir de arquivo ou zip."""
    if not img_path:
        return None

    cache_dir = os.path.join(mobile_config.get_base_dir(), "thumb_cache")
    os.makedirs(cache_dir, exist_ok=True)
    thumb_dest = os.path.join(cache_dir, f"{hashlib.md5(img_path.encode('utf-8')).hexdigest()}.jpg")

    if os.path.exists(thumb_dest) and os.path.getsize(thumb_dest) > 0:
        return thumb_dest

    # Trata caminho do Windows tentando encontrar na memória do Android
    if re.match(r"^[a-zA-Z]:", img_path) or "\\" in img_path:
        fname = os.path.basename(img_path.replace("\\", "/"))
        for candidate_root in find_drive_roots():
            cand_p = os.path.join(candidate_root, fname)
            if os.path.exists(cand_p):
                img_path = cand_p
                break

    try:
        if "::" in img_path:
            arc_p, inner_f = img_path.split("::", 1)
            inner_f = inner_f.replace("\\", "/")
            if os.path.exists(arc_p):
                with zipfile.ZipFile(arc_p, "r") as z, z.open(inner_f) as zf, Image.open(io.BytesIO(zf.read())) as im:
                    _safe_convert_and_save(im, thumb_dest)
                return thumb_dest

        if os.path.isfile(img_path) and img_path.lower().endswith((".zip", ".cbz")):
            with zipfile.ZipFile(img_path, "r") as z:
                zip_imgs = [f.filename for f in z.infolist() if not f.is_dir() and f.filename.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))]
                if not zip_imgs:
                    return None
                zip_imgs.sort(key=natural_sort_key)
                with z.open(zip_imgs[0]) as zf, Image.open(io.BytesIO(zf.read())) as im:
                    _safe_convert_and_save(im, thumb_dest)
            return thumb_dest

        first_file = img_path
        if os.path.isdir(img_path):
            imgs = [f for f in os.listdir(img_path) if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))]
            if not imgs:
                return None
            imgs.sort(key=natural_sort_key)
            first_file = os.path.join(img_path, imgs[0])

        if os.path.isfile(first_file):
            with Image.open(first_file) as im:
                _safe_convert_and_save(im, thumb_dest)
            return thumb_dest
    except Exception as e:
        print(f"[!] Erro ao gerar thumbnail para {img_path}: {e}")
    return None


def deduplicate_entries(entries):
    """Remove duplicatas lógicas (pasta + CBZ ou caminhos espelhados)."""
    best = {}
    for entry in entries:
        key = (entry.get("clean_name") or entry.get("name") or "").strip().lower()
        if not key:
            continue
        prev = best.get(key)
        if not prev:
            best[key] = entry
            continue
        sc_new = (not entry.get("is_archive", False), bool(entry.get("has_reader", False)), entry.get("mtime", 0))
        sc_old = (not prev.get("is_archive", False), bool(prev.get("has_reader", False)), prev.get("mtime", 0))
        if sc_new > sc_old:
            best[key] = entry
    return list(best.values())


def scan_directory(base_folder, seen_paths):
    """Varre pasta resolvendo symlinks e priorizando pastas sobre arquivos .cbz/.zip."""
    entries = []
    if not base_folder or not os.path.exists(base_folder):
        return entries
    img_exts = (".jpg", ".jpeg", ".png", ".webp")

    items = sorted(os.listdir(base_folder))
    items.sort(key=lambda name: (not os.path.isdir(os.path.join(base_folder, name)), name.lower()))

    for item in items:
        full_p = os.path.abspath(os.path.join(base_folder, item))
        rk = real_path_key(full_p)
        if rk in seen_paths or item.startswith(".") or item == "_ocr":
            continue

        if os.path.isdir(full_p):
            imgs = [f for f in os.listdir(full_p) if f.lower().endswith(img_exts)]
            if not imgs:
                continue
            imgs.sort(key=natural_sort_key)
            seen_paths.add(rk)
            m_id = get_manga_hash(full_p)
            has_reader = os.path.exists(os.path.join(full_p, "leitor.html"))
            cbz_p = full_p.rstrip("/\\") + ".cbz"
            has_cbz = os.path.exists(cbz_p)

            entries.append({
                "id": m_id,
                "name": item,
                "clean_name": item.replace(" [PT-BR]", "").replace("[PT-BR]", "").strip(),
                "path": full_p,
                "pages": len(imgs),
                "has_reader": has_reader,
                "has_cbz": has_cbz,
                "cbz_path": cbz_p if has_cbz else None,
                "reader_path": os.path.join(full_p, "leitor.html") if has_reader else None,
                "reader_url": f"/read/{m_id}/",
                "mtime": os.path.getmtime(full_p),
                "first_img": os.path.join(full_p, imgs[0]),
                "is_drive": is_drive_path(full_p),
                "is_archive": False
            })

        elif os.path.isfile(full_p) and item.lower().endswith((".zip", ".cbz")):
            unpacked = os.path.splitext(full_p)[0]
            if real_path_key(unpacked) in seen_paths or os.path.isdir(unpacked):
                continue
            try:
                with zipfile.ZipFile(full_p, "r") as z:
                    zip_imgs = [inf.filename for inf in z.infolist() if not inf.is_dir() and inf.filename.lower().endswith(img_exts)]
                    if not zip_imgs:
                        continue
                    zip_imgs.sort(key=natural_sort_key)
                    seen_paths.add(rk)
                    m_id = get_manga_hash(full_p)
                    clean_n = os.path.splitext(item)[0]
                    entries.append({
                        "id": m_id,
                        "name": clean_n,
                        "clean_name": clean_n.replace(" [PT-BR]", "").replace("[PT-BR]", "").strip(),
                        "path": full_p,
                        "pages": len(zip_imgs),
                        "has_reader": False,
                        "has_cbz": item.lower().endswith(".cbz"),
                        "cbz_path": full_p if item.lower().endswith(".cbz") else None,
                        "reader_url": None,
                        "mtime": os.path.getmtime(full_p),
                        "first_img": f"{full_p}::{zip_imgs[0]}",
                        "is_drive": is_drive_path(full_p),
                        "is_archive": True
                    })
            except Exception:
                pass
    return entries
