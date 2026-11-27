"""
mobile_colorizer.py - Colorização de páginas P&B no celular (mesmo modelo e técnicas da v0.8.4 do PC).
O Chaquopy não tem onnxruntime para Python: o modelo roda no ONNX Runtime oficial para Android
(classe Kotlin com.mangastudio.mobile.OnnxColorizer). Fora do Android (testes no PC), usa o
onnxruntime do Python, se instalado. O modelo (~58 MB) é baixado na primeira colorização.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import os
import re
import time
import urllib.request

import numpy as np
from PIL import Image

import mobile_color_merge
import mobile_config

MODEL_URL = "https://huggingface.co/Faridzar/manga-colorization-v2-onnx/resolve/main/manga-colorize-fp16.onnx"
MODEL_MIN_BYTES = 50 * 1024 * 1024  # o modelo tem ~59 MB; menos que isso é download incompleto
MAX_SIDE = 768  # lado maior da página no modelo: o PC usa 1024, o celular tem menos memória
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")

_backend = None


def model_path():
    return os.path.join(mobile_config.get_base_dir(), "models", "colorizer", "manga-colorize-fp16.onnx")


def download_model(dest=None, log=print):
    """Baixa num .part e só renomeia completo: uma queda de internet não deixa um modelo quebrado."""
    dest = dest or model_path()
    if os.path.exists(dest) and os.path.getsize(dest) >= MODEL_MIN_BYTES:
        return dest
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    log("Baixando o modelo de colorização (~58 MB, só na primeira vez)...")
    part = dest + ".part"
    try:
        urllib.request.urlretrieve(MODEL_URL, part)
        if os.path.getsize(part) < MODEL_MIN_BYTES:
            raise OSError("Download do modelo de colorização incompleto. Tente de novo com internet estável.")
        os.replace(part, dest)
    finally:
        if os.path.exists(part):
            os.remove(part)
    log("Modelo de colorização pronto.")
    return dest


def _android_backend(path):
    from java import jclass  # só existe no Chaquopy (Android)
    runner = jclass("com.mangastudio.mobile.OnnxColorizer")

    def run(inp):
        _, _, h, w = inp.shape
        out = runner.run(path, inp.astype("<f4").tobytes(), h, w)
        return np.frombuffer(bytes(out), dtype="<f4").reshape(1, 3, h, w)
    return run


def _python_backend(path):
    import onnxruntime as ort  # testes no PC
    session = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
    return lambda inp: session.run(["rgb"], {"input": inp})[0]


def get_backend(path=None):
    global _backend
    if _backend is None:
        path = path or download_model()
        try:
            _backend = _android_backend(path)
        except ImportError:
            _backend = _python_backend(path)
    return _backend


def release():
    """Libera a memória do modelo ao fim de cada tarefa (celular tem pouca RAM)."""
    global _backend
    _backend = None
    try:
        from java import jclass
        jclass("com.mangastudio.mobile.OnnxColorizer").release()
    except Exception:
        pass


def _model_input(gray):
    """Cinza (H, W) -> tensor (1, 5, H32, W32): canal 0 = página, 4 canais de dica zerados."""
    h, w = gray.shape
    pad_h, pad_w = (-h) % 32, (-w) % 32
    norm = np.pad(gray.astype(np.float32) / 255.0, ((0, pad_h), (0, pad_w)), mode="reflect")
    inp = np.zeros((1, 5) + norm.shape, np.float32)
    inp[0, 0] = norm
    return inp


def colorize_image(src_path, out_path, run=None):
    """Colore uma página e salva em JPG. O traço original volta por cima, em tamanho real."""
    run = run or get_backend()
    with Image.open(src_path) as im:
        gray_full = np.asarray(im.convert("L"))
    full_h, full_w = gray_full.shape
    scale = min(1.0, MAX_SIDE / float(max(full_h, full_w)))
    work = Image.fromarray(gray_full)
    if scale < 1.0:
        work = work.resize((max(32, round(full_w * scale)), max(32, round(full_h * scale))), Image.BOX)
    gray_work = np.asarray(work)
    h, w = gray_work.shape
    out = run(_model_input(gray_work))[0, :, :h, :w]
    color = (np.clip(np.transpose(out, (1, 2, 0)), 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    color = mobile_color_merge.consolidate_colors(color)
    if (h, w) != (full_h, full_w):
        color = np.asarray(Image.fromarray(color).resize((full_w, full_h), Image.BICUBIC))
    final = mobile_color_merge.merge_lineart(color, gray_full)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    ext = os.path.splitext(out_path)[1].lower()  # colorindo no lugar, a página mantém o formato do arquivo
    fmt = {".png": "PNG", ".webp": "WEBP", ".bmp": "BMP"}.get(ext, "JPEG")
    Image.fromarray(final).save(out_path, fmt, **({"quality": 92} if fmt in ("JPEG", "WEBP") else {}))
    return out_path


def _natural_key(name):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def list_pages(folder):
    return sorted((f for f in os.listdir(folder) if f.lower().endswith(IMAGE_EXTS)), key=_natural_key)


def colorized_folder_for(input_dir):
    """Capítulo colorido vai para a pasta de traduzidos, para aparecer na Biblioteca."""
    cfg = mobile_config.load_config()
    base = os.path.basename(input_dir.rstrip("/\\")).replace(" [COLORIDO]", "").strip()
    out_root = cfg.get("translated_mangas_dir") or cfg.get("output_dir") or os.path.dirname(input_dir)
    return os.path.join(out_root, f"{base} [COLORIDO]")


def colorize_folder(input_dir, output_dir=None, progress_cb=None, checkpoint=None):
    """Colore todas as páginas. progress_cb(cur, total, msg); checkpoint() permite pausar/parar.
    Com output_dir igual a input_dir, colore no lugar (capítulo que acabou de ser traduzido)."""
    pages = list_pages(input_dir)
    if not pages:
        raise ValueError("Nenhuma imagem encontrada para colorir.")
    output_dir = output_dir or colorized_folder_for(input_dir)
    log = (lambda m: progress_cb(0, len(pages), m)) if progress_cb else print
    run = get_backend(download_model(log=log))
    started, done, errors = time.time(), 0, []
    for idx, name in enumerate(pages, 1):
        if checkpoint:
            checkpoint()
        if progress_cb:
            progress_cb(idx, len(pages), f"Colorindo página {idx}/{len(pages)} ({name})...")
        out_name = name if output_dir == input_dir else os.path.splitext(name)[0] + ".jpg"
        try:
            colorize_image(os.path.join(input_dir, name), os.path.join(output_dir, out_name), run=run)
            done += 1
        except MemoryError:
            errors.append(f"{name}: memória insuficiente no celular")
        except Exception as exc:  # uma página ruim não derruba o capítulo
            errors.append(f"{name}: {exc}")
    return {"output": output_dir, "total": len(pages), "colorized": done, "errors": errors,
            "seconds": round(time.time() - started, 1)}
