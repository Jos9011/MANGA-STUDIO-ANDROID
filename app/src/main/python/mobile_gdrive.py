"""
mobile_gdrive.py - Acesso ao Google Drive do usuário pela API oficial (Drive v3)

O login acontece no Android (DriveAuthHelper.kt, Google Identity Services). O Kotlin entrega
aqui só o token de acesso (set_token), que fica apenas na memória do app: nada é salvo em disco.
Permissão pedida: somente LEITURA do Drive (drive.readonly).

- list_mangas: lista pastas e arquivos .zip/.cbz da pasta MANGAS do Drive.
- start_download: baixa a obra escolhida em segundo plano para a pasta MANGAS do celular
  (ZIP/CBZ é extraído; pasta de imagens é copiada, incluindo subpastas de capítulo).
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import os
import re
import threading
import time

import requests

API = "https://www.googleapis.com/drive/v3"
FOLDER_MIME = "application/vnd.google-apps.folder"
ARCHIVE_EXTS = (".zip", ".cbz")  # PDF não: o app do celular não tem leitor de PDF
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".avif", ".bmp")
TOKEN_TTL = 50 * 60  # o Google entrega tokens de ~60 min; renova antes disso

_STATE = {"token": None, "set_at": 0.0}
_JOB_LOCK = threading.Lock()
_JOB = {"state": "idle", "name": "", "done": 0, "total": 0, "path": "", "error": ""}


class DriveAuthError(RuntimeError):
    """Token ausente, expirado ou revogado: o app precisa pedir login de novo."""


class DriveNotFound(RuntimeError):
    """Pasta pedida não existe no Drive."""


# ---------------------------------------------------------------------------
# Token (vem do Kotlin)
# ---------------------------------------------------------------------------
def set_token(token):
    """Chamado pelo Kotlin depois do login. Token vazio = desconectar."""
    _STATE["token"] = (str(token).strip() or None) if token else None
    _STATE["set_at"] = time.time() if _STATE["token"] else 0.0
    return bool(_STATE["token"])


def clear_token():
    set_token(None)


def is_connected():
    return bool(_STATE["token"]) and (time.time() - _STATE["set_at"]) < TOKEN_TTL


def _headers():
    if not is_connected():
        raise DriveAuthError("Conecte o Google Drive novamente.")
    return {"Authorization": f"Bearer {_STATE['token']}"}


def _get(url, params=None, stream=False, timeout=60):
    resp = requests.get(url, params=params, headers=_headers(), stream=stream, timeout=timeout)
    if resp.status_code == 401:
        clear_token()
        raise DriveAuthError("Sessão do Google Drive expirou. Conecte novamente.")
    if resp.status_code != 200:
        raise RuntimeError(f"Google Drive respondeu {resp.status_code}: {resp.text[:160]}")
    return resp


# ---------------------------------------------------------------------------
# Listagem
# ---------------------------------------------------------------------------
def _escape(name):
    return str(name).replace("\\", "\\\\").replace("'", "\\'")


def list_children(folder_id, extra_query=""):
    """Todos os itens (não excluídos) de uma pasta, com paginação."""
    q = f"'{folder_id}' in parents and trashed = false" + (f" and {extra_query}" if extra_query else "")
    items, page = [], None
    while True:
        params = {"q": q, "pageSize": 200, "orderBy": "name_natural",
                  "fields": "nextPageToken, files(id, name, mimeType, size, modifiedTime)"}
        if page:
            params["pageToken"] = page
        data = _get(f"{API}/files", params=params).json()
        items.extend(data.get("files") or [])
        page = data.get("nextPageToken")
        if not page:
            return items


def find_folder(name, parent="root"):
    """ID da pasta com esse nome dentro de `parent` (None se não existir)."""
    found = list_children(parent, f"mimeType = '{FOLDER_MIME}' and name = '{_escape(name)}'")
    return found[0]["id"] if found else None


def _kind(item):
    if item.get("mimeType") == FOLDER_MIME:
        return "folder"
    name = str(item.get("name", "")).lower()
    if name.endswith(ARCHIVE_EXTS):
        return "archive"
    return None


def local_target(name, base_dir):
    """Onde a obra fica no celular (mesmo nome do Drive, sem a extensão do arquivo)."""
    clean = re.sub(r'[\\/*?:"<>|]', "_", str(name)).strip() or "Manga_Drive"
    if clean.lower().endswith(ARCHIVE_EXTS):
        clean = os.path.splitext(clean)[0]
    return os.path.join(base_dir, clean)


def _has_images(path):
    for _root, _dirs, files in os.walk(path):
        if any(f.lower().endswith(IMAGE_EXTS) for f in files):
            return True
    return False


def list_mangas(base_dir, root_name="MANGAS"):
    """Obras da pasta MANGAS do Drive, marcando as que já estão no celular."""
    root_id = find_folder(root_name)
    if not root_id:
        raise DriveNotFound(f"Pasta '{root_name}' não encontrada no seu Google Drive.")
    out = []
    for it in list_children(root_id):
        kind = _kind(it)
        if not kind:
            continue
        target = local_target(it["name"], base_dir)
        out.append({
            "id": it["id"], "name": it["name"], "kind": kind,
            "size": int(it.get("size") or 0), "modified": it.get("modifiedTime", ""),
            "local_path": target if os.path.isdir(target) and _has_images(target) else "",
        })
    return out


# ---------------------------------------------------------------------------
# Download em segundo plano
# ---------------------------------------------------------------------------
def _download_file(file_id, dest):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part"
    with _get(f"{API}/files/{file_id}", params={"alt": "media"}, stream=True, timeout=120) as resp:
        with open(tmp, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=256 * 1024):
                if chunk:
                    fh.write(chunk)
    os.replace(tmp, dest)


def _folder_plan(folder_id, dest, depth=0):
    """[(file_id, caminho_local)] das imagens da pasta e de subpastas (capítulos), até 2 níveis."""
    plan = []
    for it in list_children(folder_id):
        name = re.sub(r'[\\/*?:"<>|]', "_", str(it.get("name", ""))).strip()
        if it.get("mimeType") == FOLDER_MIME and depth < 2:
            plan.extend(_folder_plan(it["id"], os.path.join(dest, name), depth + 1))
        elif name.lower().endswith(IMAGE_EXTS):
            plan.append((it["id"], os.path.join(dest, name)))
    return plan


def _set_job(**kw):
    with _JOB_LOCK:
        _JOB.update(kw)


def job_status():
    with _JOB_LOCK:
        return dict(_JOB)


def _run_download(item, base_dir, extract_fn):
    target = local_target(item["name"], base_dir)
    try:
        if item["kind"] == "archive":
            _set_job(total=1)
            arc = os.path.join(base_dir, re.sub(r'[\\/*?:"<>|]', "_", item["name"]))
            _download_file(item["id"], arc)
            extracted = extract_fn(arc, target)
            try:
                os.remove(arc)
            except OSError:
                pass
            if not extracted:
                raise RuntimeError("Nenhuma página válida no arquivo baixado.")
            _set_job(done=1, path=extracted, state="done")
            return
        plan = _folder_plan(item["id"], target)
        if not plan:
            raise RuntimeError("A pasta do Drive não tem imagens.")
        _set_job(total=len(plan))
        for i, (fid, dest) in enumerate(plan, 1):
            if not os.path.exists(dest):
                _download_file(fid, dest)
            _set_job(done=i)
        _set_job(path=target, state="done")
    except Exception as e:
        _set_job(state="error", error=str(e))


def start_download(item, base_dir, extract_fn):
    """Inicia o download (um por vez). Devolve False se já houver um em andamento."""
    if item.get("kind") not in ("archive", "folder") or not item.get("id"):
        raise ValueError("Item inválido para download.")
    _headers()  # falha cedo se não houver login
    with _JOB_LOCK:
        if _JOB["state"] == "running":
            return False
        _JOB.update(state="running", name=item.get("name", ""), done=0, total=0, path="", error="")
    os.makedirs(base_dir, exist_ok=True)
    threading.Thread(target=_run_download, args=(item, base_dir, extract_fn), daemon=True).start()
    return True
