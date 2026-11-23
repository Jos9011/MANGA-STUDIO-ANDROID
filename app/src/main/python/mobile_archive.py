"""
mobile_archive.py - Extração segura de ZIP/CBZ preservando capítulos em subpastas
Evita que 'cap1/001.jpg' seja sobrescrito por 'cap2/001.jpg' e bloqueia caminhos maliciosos.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import os
import re
import zipfile

import mobile_config

IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
_BAD_CHARS = re.compile(r'[\\/*?:"<>|]')


def _member_parts(filename):
    """Divide o caminho interno do ZIP em partes seguras (sem '..', ocultos ou __MACOSX)."""
    parts = [p for p in filename.replace("\\", "/").split("/") if p and p != "."]
    if not parts or any(p == ".." or p.startswith(".") or p.startswith("__MACOSX") for p in parts):
        return None
    return parts


def _common_dir(dir_lists):
    """Prefixo de pastas comum a todas as imagens (ex.: a pasta raiz única do ZIP)."""
    if not dir_lists:
        return []
    common = list(dir_lists[0])
    for d in dir_lists[1:]:
        i = 0
        while i < len(common) and i < len(d) and common[i] == d[i]:
            i += 1
        common = common[:i]
    return common


def flat_names(filenames):
    """Mapeia nomes internos -> nomes planos únicos (subpastas viram prefixo 'cap1_')."""
    entries = []
    for fn in filenames:
        parts = _member_parts(fn)
        if parts and parts[-1].lower().endswith(IMG_EXTS):
            entries.append((fn, parts))
    common = _common_dir([p[:-1] for _, p in entries])
    result, used = {}, set()
    for fn, parts in entries:
        rel = parts[len(common):]
        name = _BAD_CHARS.sub("_", "_".join(rel))
        base, ext = os.path.splitext(name)
        n = 2
        while name.lower() in used:
            name = f"{base}_{n}{ext}"
            n += 1
        used.add(name.lower())
        result[fn] = name
    return result


def extract_manga_archive(archive_path, target_dir=None):
    """Extrai ZIP/CBZ para pasta organizada. Retorna a pasta ou None se não houver imagens."""
    if not os.path.exists(archive_path):
        return None

    clean_name = os.path.splitext(os.path.basename(archive_path))[0]
    clean_name = _BAD_CHARS.sub("", clean_name).strip() or "Manga_Extracted"
    if not target_dir:
        target_dir = os.path.join(mobile_config.get_base_dir(), "extracted", clean_name)
    os.makedirs(target_dir, exist_ok=True)

    with zipfile.ZipFile(archive_path, "r") as z:
        members = {m.filename: m for m in z.infolist() if not m.is_dir()}
        for inner, out_name in flat_names(list(members)).items():
            dest = os.path.join(target_dir, out_name)
            with z.open(members[inner]) as src, open(dest, "wb") as dst:
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    dst.write(chunk)

    extracted = [f for f in os.listdir(target_dir) if f.lower().endswith(IMG_EXTS)]
    return target_dir if extracted else None
