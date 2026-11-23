"""
mobile_image_io.py - Abertura de imagens à prova de codec no Android
O Pillow embutido pelo Chaquopy não decodifica todos os formatos (ex.: WebP, AVIF, HEIC).
Quando ele falha, usa o decodificador nativo do Android (BitmapFactory) e reabre em Pillow.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import io
import os
from PIL import Image

MAX_NATIVE_PIXELS = 48_000_000  # acima disso reduz pela metade (tiras longas de webtoon)


def sniff_format(path):
    """Identifica o formato real pelos bytes iniciais (independe da extensão do arquivo)."""
    try:
        with open(path, "rb") as f:
            head = f.read(32)
    except OSError:
        return "ilegível"
    if not head:
        return "arquivo vazio (0 bytes)"
    if head.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if head.startswith(b"\x89PNG"):
        return "PNG"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "WebP"
    if head[4:8] == b"ftyp":
        brand = head[8:12].decode("ascii", "replace")
        if brand.startswith("avi"):
            return "AVIF"
        if brand in ("heic", "heix", "hevc", "mif1", "msf1"):
            return "HEIC/HEIF"
        return f"ISO-BMFF ({brand})"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "GIF"
    if head.startswith(b"BM"):
        return "BMP"
    if head.lstrip().startswith((b"<", b"{")):
        return "HTML/texto (download incompleto ou página de erro)"
    return f"desconhecido ({head[:8].hex()})"


def _android_decode_to_bytes(path):
    """Decodifica com BitmapFactory (Android) e devolve JPEG em bytes; None fora do Android."""
    try:
        from java import jclass  # Disponível apenas dentro do Chaquopy
    except ImportError:
        return None

    BitmapFactory = jclass("android.graphics.BitmapFactory")
    Options = jclass("android.graphics.BitmapFactory$Options")
    CompressFormat = jclass("android.graphics.Bitmap$CompressFormat")
    ByteArrayOutputStream = jclass("java.io.ByteArrayOutputStream")

    bounds = Options()
    bounds.inJustDecodeBounds = True
    BitmapFactory.decodeFile(path, bounds)
    if bounds.outWidth <= 0 or bounds.outHeight <= 0:
        return None

    opts = Options()
    opts.inSampleSize = 2 if bounds.outWidth * bounds.outHeight > MAX_NATIVE_PIXELS else 1
    bitmap = BitmapFactory.decodeFile(path, opts)
    if bitmap is None:
        return None
    try:
        out = ByteArrayOutputStream()
        bitmap.compress(CompressFormat.JPEG, 97, out)
        return bytes(out.toByteArray())
    finally:
        bitmap.recycle()


def open_rgb(path):
    """
    Abre qualquer página como PIL.Image RGB (carregada em memória).
    Ordem: Pillow -> decodificador nativo do Android -> erro claro com o formato real.
    """
    pil_err = None
    try:
        with Image.open(path) as im:
            return _to_rgb(im)
    except Exception as e:  # UnidentifiedImageError, OSError de codec ausente etc.
        pil_err = e

    try:
        data = _android_decode_to_bytes(path)
    except Exception as e:
        data = None
        pil_err = f"{pil_err}; Android: {e}"
    if data:
        with Image.open(io.BytesIO(data)) as im:
            return _to_rgb(im)

    fmt = sniff_format(path)
    raise ValueError(
        f"Não foi possível abrir a imagem '{os.path.basename(path)}' (formato real: {fmt}). "
        f"Converta a página para JPG/PNG ou baixe-a novamente. Detalhe: {pil_err}"
    )


def _to_rgb(im):
    """Converte para RGB achatando transparência sobre fundo branco (papel do mangá)."""
    if im.mode in ("RGBA", "LA", "P"):
        rgba = im.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.split()[-1])
        return bg
    return im.convert("RGB")
