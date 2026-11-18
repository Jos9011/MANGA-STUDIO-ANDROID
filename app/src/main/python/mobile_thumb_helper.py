"""
mobile_thumb_helper.py - Extração e Miniaturas de Capas à Prova de Falhas no Android
Tenta redimensionar via Pillow; se o codec (ex: WEBP) falhar no Chaquopy, envia os
bytes originais direto para a WebView Chromium renderizar nativamente em hardware.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import hashlib
import io
import os
import re
import zipfile
from PIL import Image

import mobile_config
import mobile_drive_helper

IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif")
_LANCZOS = getattr(getattr(Image, "Resampling", Image), "LANCZOS", Image.BICUBIC)


def _guess_mime(name):
    low = str(name or "").lower()
    if low.endswith(".png"):
        return "image/png"
    if low.endswith(".webp"):
        return "image/webp"
    if low.endswith(".gif"):
        return "image/gif"
    if low.endswith(".bmp"):
        return "image/bmp"
    return "image/jpeg"


def _open_zip_member_bytes(z, inner_f):
    """Lê membro do ZIP tentando o nome exato, barras normalizadas ou 1ª imagem."""
    names = {inf.filename for inf in z.infolist() if not inf.is_dir()}
    for cand in (inner_f, inner_f.replace("\\", "/"), inner_f.replace("/", "\\")):
        if cand in names:
            with z.open(cand) as zf:
                return zf.read(), _guess_mime(cand)
    imgs = sorted(
        [n for n in names if n.lower().endswith(IMG_EXTS)],
        key=mobile_drive_helper.natural_sort_key,
    )
    if imgs:
        with z.open(imgs[0]) as zf:
            return zf.read(), _guess_mime(imgs[0])
    return None, None


def extract_cover_bytes(img_path):
    """Retorna (raw_bytes, mimetype) da capa a partir de ZIP::membro, ZIP, pasta ou arquivo."""
    if not img_path:
        return None, None

    if "::" in img_path:
        arc_p, inner_f = img_path.split("::", 1)
        if os.path.isfile(arc_p):
            try:
                with zipfile.ZipFile(arc_p, "r") as z:
                    return _open_zip_member_bytes(z, inner_f)
            except Exception:
                return None, None
        return None, None

    if os.path.isfile(img_path) and img_path.lower().endswith((".zip", ".cbz")):
        try:
            with zipfile.ZipFile(img_path, "r") as z:
                return _open_zip_member_bytes(z, "")
        except Exception:
            return None, None

    target_file = img_path
    if os.path.isdir(img_path):
        imgs = [f for f in os.listdir(img_path) if f.lower().endswith(IMG_EXTS)]
        if not imgs:
            for d in sorted(os.listdir(img_path), key=mobile_drive_helper.natural_sort_key):
                sub = os.path.join(img_path, d)
                if os.path.isdir(sub) and not d.startswith("."):
                    s_imgs = [f for f in os.listdir(sub) if f.lower().endswith(IMG_EXTS)]
                    if s_imgs:
                        s_imgs.sort(key=mobile_drive_helper.natural_sort_key)
                        target_file = os.path.join(sub, s_imgs[0])
                        break
        else:
            imgs.sort(key=mobile_drive_helper.natural_sort_key)
            target_file = os.path.join(img_path, imgs[0])

    if os.path.isfile(target_file):
        try:
            with open(target_file, "rb") as f:
                return f.read(), _guess_mime(target_file)
        except Exception:
            return None, None
    return None, None


def get_thumbnail_or_raw(img_path):
    """
    Retorna ('file', thumb_path, 'image/jpeg') se miniatura JPEG foi gerada/cacheada,
    ('bytes', raw_bytes, mime) se Pillow falhou mas os bytes reais existem,
    ou (None, None, None) se o arquivo não existir.
    """
    if not img_path:
        return None, None, None

    cache_dir = os.path.join(mobile_config.get_base_dir(), "thumb_cache")
    os.makedirs(cache_dir, exist_ok=True)
    thumb_dest = os.path.join(cache_dir, f"{hashlib.md5(img_path.encode('utf-8')).hexdigest()}.jpg")
    if os.path.exists(thumb_dest) and os.path.getsize(thumb_dest) > 0:
        return "file", thumb_dest, "image/jpeg"

    raw_bytes, mime = extract_cover_bytes(img_path)
    if not raw_bytes:
        return None, None, None

    try:
        with Image.open(io.BytesIO(raw_bytes)) as im:
            if im.mode in ("RGBA", "LA", "P"):
                im_rgba = im.convert("RGBA")
                bg = Image.new("RGB", im_rgba.size, (24, 24, 24))
                bg.paste(im_rgba, mask=im_rgba.split()[-1])
                im_final = bg
            else:
                im_final = im.convert("RGB")
            im_final.thumbnail((320, 460), _LANCZOS)
            im_final.save(thumb_dest, "JPEG", quality=85)
        if os.path.exists(thumb_dest) and os.path.getsize(thumb_dest) > 0:
            return "file", thumb_dest, "image/jpeg"
    except Exception as e:
        print(f"[!] Pillow fallback para bytes nativos em {img_path}: {e}")

    # Fallback nativo: entrega imagem original (WEBP/PNG/JPG) direto para o Chromium da WebView
    return "bytes", raw_bytes, mime
