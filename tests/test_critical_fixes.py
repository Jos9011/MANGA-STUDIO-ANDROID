"""
tests/test_critical_fixes.py - Regressões das correções críticas v0.7.4 Beta (APK v1.0.10)
Falhas silenciosas, fallback entre provedores, token/caminhos, ordem de páginas e ZIP multi-capítulo.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from unittest import mock
from PIL import Image

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app", "src", "main", "python")))

import mobile_archive
import mobile_config
import mobile_security
import mobile_translator
import mobile_vision_api
from mobile_server import app

FAKE_CFG = dict(mobile_config.get_default_config(), provider="groq",
                groq_api_key="gk-test", gemini_api_key="gm-test")


def _make_img(path, size=(200, 300)):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new("RGB", size, (255, 255, 255)).save(path)


class VisionParsingTests(unittest.TestCase):

    def test_truncated_json_raises_instead_of_empty(self):
        truncated = '[{"box_2d":[1,2,3,4],"translation":"Olá"},{"box_2d":[5,6,7,8],"translation":"Tud'
        with self.assertRaises(mobile_vision_api.VisionResponseError):
            mobile_vision_api.parse_bubbles(truncated)
        self.assertEqual(mobile_vision_api.extract_json_bubbles(truncated), [])

    def test_empty_list_is_valid(self):
        self.assertEqual(mobile_vision_api.parse_bubbles("```json\n[]\n```"), [])

    def test_fallback_to_next_provider_when_preferred_fails(self):
        ok = [{"box_2d": [0, 0, 100, 100], "translation": "Oi"}]
        groq = mock.Mock(side_effect=RuntimeError("Groq 400"))
        gem = mock.Mock(return_value=ok)
        with mock.patch.dict(mobile_vision_api._CALLS, {"groq": (groq, "a", "b"), "gemini": (gem, "a", "b")}):
            self.assertEqual(mobile_vision_api.call_vision_api("b64", FAKE_CFG), ok)
        groq.assert_called_once()  # provedor preferido tentado primeiro
        gem.assert_called_once()

    def test_all_providers_fail_reports_every_error(self):
        with mock.patch.dict(mobile_vision_api._CALLS, {
            "groq": (mock.Mock(side_effect=RuntimeError("Groq 429")), "a", "b"),
            "gemini": (mock.Mock(side_effect=RuntimeError("Gemini 403")), "a", "b"),
        }):
            with self.assertRaises(RuntimeError) as ctx:
                mobile_vision_api.call_vision_api("b64", FAKE_CFG)
        self.assertIn("Groq 429", str(ctx.exception))
        self.assertIn("Gemini 403", str(ctx.exception))


class CoordinateTests(unittest.TestCase):

    def test_scale_0_1000(self):
        self.assertEqual(mobile_translator.box_to_pixels([100, 200, 300, 400], 700, 1000, 1400, 2000),
                         (280, 200, 560, 600))

    def test_pixel_coords_of_sent_image(self):
        # Coordenadas > 1000 = pixels da imagem enviada (700x1400), original 1400x2800
        self.assertEqual(mobile_translator.box_to_pixels([1200, 100, 1300, 300], 700, 1400, 1400, 2800),
                         (200, 2400, 600, 2600))

    def test_invalid_boxes(self):
        self.assertIsNone(mobile_translator.box_to_pixels([1, 2, 3], 10, 10, 10, 10))
        self.assertIsNone(mobile_translator.box_to_pixels(["a", 2, 3, 4], 10, 10, 10, 10))


class PagesAndArchiveTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_natural_page_order_and_subfolders(self):
        for n in ("1", "2", "10"):
            _make_img(os.path.join(self.tmp, f"{n}.jpg"))
        _make_img(os.path.join(self.tmp, "cap2", "1.jpg"))
        names = [out for _, out in mobile_translator.list_page_images(self.tmp)]
        self.assertEqual(names, ["1.jpg", "2.jpg", "10.jpg", "cap2_1.jpg"])

    def test_multi_chapter_zip_keeps_all_pages(self):
        arc = os.path.join(self.tmp, "obra.cbz")
        src = os.path.join(self.tmp, "p.jpg")
        _make_img(src)
        with zipfile.ZipFile(arc, "w") as z:
            for ch in ("Obra/cap1", "Obra/cap2"):
                z.write(src, f"{ch}/001.jpg")
                z.write(src, f"{ch}/002.jpg")
            z.write(src, "__MACOSX/Obra/._001.jpg")
            z.write(src, "../../evil.jpg")
        out = mobile_archive.extract_manga_archive(arc, os.path.join(self.tmp, "out"))
        self.assertEqual(sorted(os.listdir(out)),
                         ["cap1_001.jpg", "cap1_002.jpg", "cap2_001.jpg", "cap2_002.jpg"])

    def test_translation_reports_failures_instead_of_success(self):
        for n in ("1", "2", "3"):
            _make_img(os.path.join(self.tmp, "in", f"{n}.jpg"))
        out_dir = os.path.join(self.tmp, "out")
        calls = {"n": 0}

        def fake_vision(b64, cfg):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("Groq 400: model does not support images")
            return []

        logs = []
        with mock.patch.object(mobile_config, "load_config", return_value=FAKE_CFG), \
             mock.patch.object(mobile_translator, "call_vision_api", side_effect=fake_vision):
            summary = mobile_translator.translate_manga_folder(
                os.path.join(self.tmp, "in"), out_dir, progress_cb=lambda *a, **k: logs.append(a[3]))
        self.assertEqual((summary["translated"], summary["failed"]), (2, 1))
        self.assertIn("model does not support images", summary["errors"][0]["error"])
        self.assertTrue(any("NÃO traduzida" in m for m in logs))
        self.assertIn("falhas", mobile_translator.summary_message(summary))

    def test_all_pages_failing_raises_and_leaves_no_fake_output(self):
        _make_img(os.path.join(self.tmp, "in", "1.jpg"))
        out_dir = os.path.join(self.tmp, "out")
        with mock.patch.object(mobile_config, "load_config", return_value=FAKE_CFG), \
             mock.patch.object(mobile_translator, "call_vision_api", side_effect=RuntimeError("cota esgotada")):
            with self.assertRaises(RuntimeError) as ctx:
                mobile_translator.translate_manga_folder(os.path.join(self.tmp, "in"), out_dir)
        self.assertIn("cota esgotada", str(ctx.exception))
        self.assertFalse(os.path.exists(os.path.join(out_dir, "1.jpg")))


class SecurityTests(unittest.TestCase):

    def setUp(self):
        mobile_security.set_token("segredo-teste")
        self.client = app.test_client()

    def tearDown(self):
        mobile_security._STATE["token"] = ""

    def test_api_requires_token(self):
        self.assertEqual(self.client.get("/api/config").status_code, 403)
        self.assertEqual(self.client.get("/api/health").status_code, 200)

    def test_token_in_url_sets_cookie_for_next_requests(self):
        self.assertEqual(self.client.get("/api/version?token=segredo-teste").status_code, 200)
        self.assertEqual(self.client.get("/api/version").status_code, 200)

    def test_wrong_token_rejected(self):
        self.assertEqual(self.client.get("/api/config?token=errado").status_code, 403)

    def test_delete_outside_manga_folders_blocked(self):
        tmp = tempfile.mkdtemp()
        try:
            r = self.client.post("/api/delete_manga?token=segredo-teste", json={"path": tmp})
            self.assertEqual(r.status_code, 403)
            self.assertTrue(os.path.isdir(tmp))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_download_arbitrary_file_blocked(self):
        cfg_path = mobile_config.get_config_path()
        mobile_config.save_config(mobile_config.load_config())
        r = self.client.get("/api/download_cbz", query_string={"path": cfg_path, "token": "segredo-teste"})
        self.assertEqual(r.status_code, 403)

    def test_is_within(self):
        root = os.path.realpath(tempfile.gettempdir())
        self.assertTrue(mobile_security.is_within(os.path.join(root, "a", "b"), [root]))
        self.assertFalse(mobile_security.is_within(root, [root]))
        self.assertFalse(mobile_security.is_within(os.path.join(root, "..", "x"), [root]))


if __name__ == "__main__":
    unittest.main()
