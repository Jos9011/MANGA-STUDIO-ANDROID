"""
test_mobile_colorize.py - Colorização no celular (v1.0.16-mobile, técnicas da v0.8.4 do PC).
O modelo é falso (cor fixa) para o teste rodar sem internet; a comparação com o OpenCV do PC
foi feita à parte (diferença média de 1,4 em 255 numa página real).
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app", "src", "main", "python")))

import mobile_color_merge as cm  # noqa: E402
import mobile_colorizer  # noqa: E402

PEACH = np.array([235, 190, 150], np.uint8)  # RGB


def fake_backend(inp):
    """Modelo falso: devolve pele pêssego em toda a página."""
    _, _, h, w = inp.shape
    return np.broadcast_to((PEACH / 255.0).astype(np.float32)[None, :, None, None], (1, 3, h, w)).copy()


class TestLabLikeOpenCV(unittest.TestCase):
    def test_reference_values(self):
        px = np.array([[[255, 255, 255], [0, 0, 0], [255, 0, 0]]], np.uint8)
        lab = cm.rgb_to_lab(px)[0]
        np.testing.assert_allclose(lab[0], (255, 128, 128), atol=1.0)
        np.testing.assert_allclose(lab[1], (0, 128, 128), atol=1.0)
        np.testing.assert_allclose(lab[2], (136, 208, 195), atol=1.5)  # valor do cv2 para vermelho puro

    def test_roundtrip(self):
        rgb = np.random.default_rng(3).integers(0, 256, (32, 32, 3), dtype=np.uint8)
        self.assertLessEqual(int(np.abs(cm.lab_to_rgb(cm.rgb_to_lab(rgb)).astype(int) - rgb).max()), 1)


class TestColorTechniques(unittest.TestCase):
    def test_paper_keeps_skin_tone_and_ink_stays_black(self):
        color = np.broadcast_to(PEACH, (40, 1500, 3)).copy()
        gray = np.full((40, 1500), 255, np.uint8)
        gray[:, 700:704] = 0
        out = cm.merge_lineart(color, gray).astype(int)
        r, g, b = out[20, 100]
        self.assertGreater(r, b + 25)  # continua pele, não estoura para branco
        self.assertLess(int(out[20, 700:704].max()), 30)

    def test_screentone_becomes_smooth(self):
        gray = np.full((80, 1500), 255, np.uint8)
        gray[::3, ::3] = 0
        out = cm.merge_lineart(np.broadcast_to(PEACH, (80, 1500, 3)).copy(), gray)[10:70, 100:1400]
        self.assertLess(max(float(out[..., c].std()) for c in range(3)), 4)

    def test_palette_evens_out_one_garment(self):
        rng = np.random.default_rng(7)
        lab = np.zeros((300, 600, 3), np.float32)
        lab[..., 0] = 150
        lab[:, :300, 1:] = (150, 110)
        lab[:, 300:, 1:] = (140, 150)
        noise = np.asarray(Image.fromarray(rng.normal(128, 40, (300, 600)).clip(0, 255).astype(np.uint8))
                           .resize((60, 30)).resize((600, 300), Image.BICUBIC), np.float32) - 128
        lab[..., 1] += noise * 0.6
        lab[..., 2] -= noise * 0.6
        img = cm.lab_to_rgb(lab)
        before = cm.rgb_to_lab(img)[:, 20:280, 1:].reshape(-1, 2).std(0).max()
        after = cm.rgb_to_lab(cm.consolidate_colors(img))[:, 20:280, 1:].reshape(-1, 2).std(0).max()
        self.assertLess(after, before * 0.9)


class TestColorizer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_interrupted_download_leaves_nothing(self):
        dest = os.path.join(self.tmp, "m", "model.onnx")

        def broken(url, path):
            with open(path, "wb") as f:
                f.write(b"x" * 1024)
            raise OSError("conexão perdida")

        with mock.patch("urllib.request.urlretrieve", side_effect=broken):
            with self.assertRaises(OSError):
                mobile_colorizer.download_model(dest, log=lambda m: None)
        self.assertEqual(os.listdir(os.path.dirname(dest)), [])

    def test_page_keeps_size_and_large_page_is_reduced_for_model(self):
        src = os.path.join(self.tmp, "p.png")
        Image.new("L", (900, 1300), 255).save(src)
        seen = []
        out = mobile_colorizer.colorize_image(src, os.path.join(self.tmp, "o.jpg"),
                                              run=lambda inp: (seen.append(inp.shape), fake_backend(inp))[1])
        with Image.open(out) as im:
            self.assertEqual(im.size, (900, 1300))
        self.assertLessEqual(max(seen[0][2:]), 800)  # lado maior <= 768 + arredondamento para múltiplo de 32
        self.assertEqual(seen[0][2] % 32, 0)


class TestColorizeRoutes(unittest.TestCase):
    def setUp(self):
        import mobile_server
        import mobile_config
        self.tmp = tempfile.mkdtemp()
        self.chapter = os.path.join(self.tmp, "raw", "Obra Ch.1")
        os.makedirs(self.chapter)
        for name in ("01.png", "02.jpg"):
            Image.new("L", (300, 420), 255).save(os.path.join(self.chapter, name))
        self.out_root = os.path.join(self.tmp, "trad")
        self.client = mobile_server.app.test_client()
        self.cfg_patch = mock.patch.object(mobile_config, "load_config", return_value={"translated_mangas_dir": self.out_root})
        self.cfg_patch.start()
        self.backend_patch = mock.patch.object(mobile_colorizer, "get_backend", return_value=fake_backend)
        self.backend_patch.start()
        self.dl_patch = mock.patch.object(mobile_colorizer, "download_model", return_value="fake.onnx")
        self.dl_patch.start()

    def tearDown(self):
        mock.patch.stopall()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _wait(self):
        for _ in range(100):
            p = self.client.get("/api/progress").get_json()
            if p["status"] not in ("running", "paused"):
                return p
            time.sleep(0.1)
        self.fail("tarefa não terminou")

    def test_colorize_only_goes_to_translated_folder(self):
        r = self.client.post("/api/colorize", json={"path": self.chapter})
        self.assertEqual(r.status_code, 200)
        p = self._wait()
        self.assertEqual(p["status"], "done", p)
        self.assertEqual(sorted(os.listdir(os.path.join(self.out_root, "Obra Ch.1 [COLORIDO]"))), ["01.jpg", "02.jpg"])

    def test_translate_then_colorize_in_place(self):
        out = os.path.join(self.out_root, "Obra Ch.1 [PT-BR]")

        def fake_translate(folder, progress_cb=None):
            shutil.copytree(folder, out)
            return {"output": out, "total": 2, "translated": 2, "failed": 0, "errors": []}

        with mock.patch("mobile_translator.translate_manga_folder", side_effect=fake_translate), \
                mock.patch("mobile_translator.summary_message", return_value="Traduzido."):
            r = self.client.post("/api/start", json={"path": self.chapter, "colorize": True})
            self.assertEqual(r.status_code, 200)
            p = self._wait()
        self.assertEqual(p["status"], "done", p)
        self.assertIn("Colorização concluída: 2 de 2", p["message"])
        with Image.open(os.path.join(out, "01.png")) as im:
            self.assertEqual(im.format, "PNG")  # colorindo no lugar, o .png continua PNG de verdade
            r_, g_, b_ = im.convert("RGB").getpixel((150, 200))
        self.assertGreater(r_, b_ + 25)  # página traduzida agora está colorida

    def test_invalid_path(self):
        self.assertEqual(self.client.post("/api/colorize", json={"path": "/nao/existe"}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
