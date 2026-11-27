"""
tests/test_mobile_gdrive.py - Google Drive na Biblioteca do app: token, listagem, download e rotas.
A API do Google é simulada (requests.get); o login real só pode ser testado no aparelho.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
import zipfile
from unittest import mock

from PIL import Image

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app", "src", "main", "python")))

import mobile_config
import mobile_drive_helper
import mobile_gdrive
import mobile_security
from mobile_server import app

FOLDER = mobile_gdrive.FOLDER_MIME


def _jpg_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (40, 60), "white").save(buf, "JPEG")
    return buf.getvalue()


def _zip_bytes():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("01.jpg", _jpg_bytes())
        z.writestr("02.jpg", _jpg_bytes())
    return buf.getvalue()


class _Resp:
    def __init__(self, status=200, data=None, content=b""):
        self.status_code, self._data, self._content = status, data or {}, content
        self.text = json.dumps(self._data)

    def json(self):
        return self._data

    def iter_content(self, chunk_size=1):
        for i in range(0, len(self._content), chunk_size):
            yield self._content[i:i + chunk_size]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeDrive:
    """Drive em memória: {pasta_id: [itens]} e {arquivo_id: bytes}."""

    def __init__(self, tree, blobs):
        self.tree, self.blobs, self.calls = tree, blobs, []

    def get(self, url, params=None, headers=None, stream=False, timeout=None):
        self.calls.append((url, dict(params or {}), dict(headers or {})))
        if url.endswith("/files"):
            q = params["q"]
            parent = q.split("'")[1]
            items = list(self.tree.get(parent, []))
            if "name = '" in q:
                wanted = q.split("name = '")[1].rsplit("'", 1)[0]
                items = [i for i in items if i["name"] == wanted and i["mimeType"] == FOLDER]
            if not params.get("pageToken") and len(items) > 2 and parent == "mangas":
                return _Resp(data={"files": items[:2], "nextPageToken": "p2"})
            if params.get("pageToken"):
                items = items[2:]
            return _Resp(data={"files": items})
        file_id = url.rsplit("/", 1)[1]
        return _Resp(content=self.blobs[file_id])


def _drive():
    tree = {
        "root": [{"id": "mangas", "name": "MANGAS", "mimeType": FOLDER}],
        "mangas": [
            {"id": "f1", "name": "Obra Pasta Ch.1", "mimeType": FOLDER},
            {"id": "z1", "name": "Obra Zip Ch.2.zip", "mimeType": "application/zip", "size": "2048"},
            {"id": "p1", "name": "Livro.pdf", "mimeType": "application/pdf"},
            {"id": "t1", "name": "notas.txt", "mimeType": "text/plain"},
        ],
        "f1": [{"id": "i1", "name": "01.jpg", "mimeType": "image/jpeg"},
               {"id": "sub", "name": "extra", "mimeType": FOLDER}],
        "sub": [{"id": "i2", "name": "02.png", "mimeType": "image/png"}],
    }
    blobs = {"z1": _zip_bytes(), "i1": _jpg_bytes(), "i2": _jpg_bytes()}
    return FakeDrive(tree, blobs)


class TestToken(unittest.TestCase):
    def tearDown(self):
        mobile_gdrive.clear_token()

    def test_set_clear_and_expiry(self):
        self.assertFalse(mobile_gdrive.is_connected())
        self.assertTrue(mobile_gdrive.set_token("ya29.teste"))
        self.assertTrue(mobile_gdrive.is_connected())
        mobile_gdrive._STATE["set_at"] = time.time() - mobile_gdrive.TOKEN_TTL - 1
        self.assertFalse(mobile_gdrive.is_connected())
        self.assertFalse(mobile_gdrive.set_token(""))
        with self.assertRaises(mobile_gdrive.DriveAuthError):
            mobile_gdrive._headers()


class TestDrive(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.base = os.path.join(self.tmp, "MANGAS")
        mobile_gdrive.set_token("ya29.teste")
        mobile_gdrive._JOB.update(state="idle")
        self.fake = _drive()
        self.patch = mock.patch.object(mobile_gdrive.requests, "get", side_effect=self.fake.get)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        mobile_gdrive.clear_token()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _wait_job(self):
        for _ in range(200):
            st = mobile_gdrive.job_status()
            if st["state"] != "running":
                return st
            time.sleep(0.02)
        self.fail("download não terminou")

    def test_list_only_folders_and_zips_with_pagination(self):
        items = mobile_gdrive.list_mangas(self.base)
        self.assertEqual([(i["name"], i["kind"]) for i in items],
                         [("Obra Pasta Ch.1", "folder"), ("Obra Zip Ch.2.zip", "archive")])
        self.assertEqual(items[1]["size"], 2048)
        self.assertTrue(all(c[2]["Authorization"] == "Bearer ya29.teste" for c in self.fake.calls))
        self.assertTrue(any(c[1].get("pageToken") == "p2" for c in self.fake.calls))

    def test_missing_root_folder(self):
        self.fake.tree["root"] = []
        with self.assertRaises(mobile_gdrive.DriveNotFound):
            mobile_gdrive.list_mangas(self.base)

    def test_expired_token_from_google_clears_session(self):
        self.patch.stop()
        with mock.patch.object(mobile_gdrive.requests, "get", return_value=_Resp(401, {"error": "invalid"})):
            with self.assertRaises(mobile_gdrive.DriveAuthError):
                mobile_gdrive.list_mangas(self.base)
        self.patch.start()
        self.assertFalse(mobile_gdrive.is_connected())

    def test_download_zip_extracts_into_mangas_folder(self):
        self.assertTrue(mobile_gdrive.start_download(
            {"id": "z1", "name": "Obra Zip Ch.2.zip", "kind": "archive"}, self.base,
            mobile_drive_helper.extract_manga_archive))
        st = self._wait_job()
        self.assertEqual(st["state"], "done", st)
        self.assertEqual(st["path"], os.path.join(self.base, "Obra Zip Ch.2"))
        self.assertEqual(sorted(os.listdir(st["path"])), ["01.jpg", "02.jpg"])
        self.assertFalse(os.path.exists(os.path.join(self.base, "Obra Zip Ch.2.zip")))
        listed = {i["name"]: i["local_path"] for i in mobile_gdrive.list_mangas(self.base)}
        self.assertEqual(listed["Obra Zip Ch.2.zip"], st["path"])

    def test_download_folder_with_subfolder(self):
        mobile_gdrive.start_download({"id": "f1", "name": "Obra Pasta Ch.1", "kind": "folder"},
                                     self.base, mobile_drive_helper.extract_manga_archive)
        st = self._wait_job()
        self.assertEqual((st["state"], st["done"], st["total"]), ("done", 2, 2))
        self.assertTrue(os.path.exists(os.path.join(self.base, "Obra Pasta Ch.1", "01.jpg")))
        self.assertTrue(os.path.exists(os.path.join(self.base, "Obra Pasta Ch.1", "extra", "02.png")))

    def test_only_one_download_at_a_time_and_invalid_items(self):
        mobile_gdrive._JOB.update(state="running")
        self.assertFalse(mobile_gdrive.start_download({"id": "z1", "name": "x.zip", "kind": "archive"},
                                                      self.base, None))
        mobile_gdrive._JOB.update(state="idle")
        with self.assertRaises(ValueError):
            mobile_gdrive.start_download({"id": "p1", "name": "Livro.pdf", "kind": None}, self.base, None)

    def test_broken_zip_reports_error(self):
        self.fake.blobs["z1"] = b"isto nao e zip"
        mobile_gdrive.start_download({"id": "z1", "name": "Ruim.zip", "kind": "archive"}, self.base,
                                     mobile_drive_helper.extract_manga_archive)
        self.assertEqual(self._wait_job()["state"], "error")


class TestRoutes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        mobile_security.set_token("segredo-teste")
        self.client = app.test_client()
        self.client.get("/api/version?token=segredo-teste")  # grava o cookie de sessão
        cfg = {"input_dir": os.path.join(self.tmp, "MANGAS")}
        self.cfg = mock.patch.object(mobile_config, "load_config", return_value=cfg)
        self.cfg.start()
        mobile_gdrive._JOB.update(state="idle")

    def tearDown(self):
        self.cfg.stop()
        mobile_gdrive.clear_token()
        mobile_security._STATE["token"] = ""
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_requires_app_token(self):
        self.assertEqual(app.test_client().get("/api/gdrive/status").status_code, 403)

    def test_not_connected_returns_auth_error(self):
        self.assertFalse(self.client.get("/api/gdrive/status").get_json()["connected"])
        r = self.client.get("/api/gdrive/list")
        self.assertEqual((r.status_code, r.get_json()["error"]), (401, "auth"))
        r = self.client.post("/api/gdrive/download", json={"id": "z1", "name": "a.zip", "kind": "archive"})
        self.assertEqual(r.status_code, 401)

    def test_list_and_download_flow(self):
        mobile_gdrive.set_token("ya29.teste")
        with mock.patch.object(mobile_gdrive.requests, "get", side_effect=_drive().get):
            r = self.client.get("/api/gdrive/list")
            self.assertEqual(r.status_code, 200)
            self.assertEqual(len(r.get_json()["items"]), 2)
            r = self.client.post("/api/gdrive/download", json={"id": "z1", "name": "Obra.zip", "kind": "archive"})
            self.assertEqual(r.status_code, 200)
            for _ in range(200):
                st = self.client.get("/api/gdrive/download_status").get_json()
                if st["state"] != "running":
                    break
                time.sleep(0.02)
        self.assertEqual(st["state"], "done", st)
        self.assertTrue(self.client.post("/api/gdrive/disconnect").get_json()["connected"] is False)
        self.assertFalse(mobile_gdrive.is_connected())


class TestTemplate(unittest.TestCase):
    def test_drive_section_only_in_android_app(self):
        # Desde a v1.0.16 a interface fica em templates/partials e static/js (visual da v0.8.4 do PC)
        studio = os.path.join(os.path.dirname(__file__), "..", "app", "src", "main", "python", "studio")
        parts = []
        for rel in ("templates/partials/library.html", "templates/index.html", "static/js/gdrive.js"):
            with open(os.path.join(studio, rel), encoding="utf-8") as f:
                parts.append(f.read())
        html, index, js = parts
        self.assertIn('<div id="gdrive-section" hidden>', html)
        self.assertIn("'gdrive'", index)
        self.assertIn("window.MangaDrive && window.MangaDrive.isAvailable()", js)
        self.assertIn("window.onDriveAuthResult = function", js)
        self.assertIn("gdriveItems.filter(it => mangaMatchesSearch(it.name, q))", js)
        for text in parts:
            self.assertNotIn("set_token", text)  # o token nunca passa pela página

if __name__ == "__main__":
    unittest.main()
