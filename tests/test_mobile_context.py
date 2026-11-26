"""
tests/test_mobile_context.py - v1.0.15: contexto entre páginas e espera de cota no tradutor do APK.
A IA Vision é simulada; nada sai para a internet.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

from PIL import Image

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app", "src", "main", "python")))

import mobile_config
import mobile_ficha
import mobile_translator
import quota_wait

CFG = {"gemini_api_keys": ["AIza-teste"], "output_dir": "", "context_pages": 2, "max_image_dim": 400}


class TestMobileContext(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, "Obra Ch.1")
        os.makedirs(self.src)
        for i in (1, 2, 3):
            Image.new("RGB", (300, 400), "white").save(os.path.join(self.src, f"{i:02d}.png"))
        self.cfg = dict(CFG, output_dir=os.path.join(self.tmp, "out"))
        self.patches = [
            mock.patch.object(mobile_config, "load_config", return_value=self.cfg),
            mock.patch.object(mobile_ficha, "load_chapter_ficha", return_value={}),
            mock.patch.object(mobile_ficha, "prompt_block", return_value=""),
            mock.patch.object(mobile_ficha, "update_after_chapter", return_value=False),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _bubble(self, orig, trans):
        return {"box_2d": [100, 100, 300, 600], "original": orig, "translation": trans}

    def test_next_page_prompt_carries_previous_lines(self):
        prompts = []
        script = [[self._bubble("WHERE IS THE KEY?", "Cadê a chave?")],
                  [self._bubble("IN THE DRAWER.", "Na gaveta.")],
                  []]

        def fake_vision(b64, cfg, extra_prompt=""):
            prompts.append(extra_prompt)
            return script.pop(0)
        with mock.patch.object(mobile_translator, "call_vision_api", side_effect=fake_vision):
            res = mobile_translator.translate_manga_folder(self.src)
        self.assertEqual(res["translated"], 3)
        self.assertEqual(prompts[0], "")
        self.assertIn("(pág 1) WHERE IS THE KEY? => Cadê a chave?", prompts[1])
        self.assertIn("(pág 2) IN THE DRAWER. => Na gaveta.", prompts[2])

    def test_waits_for_quota_and_retries_the_same_page(self):
        calls = {"n": 0}
        waits = []

        def fake_vision(b64, cfg, extra_prompt=""):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("Falha em todas as chaves Gemini (m): Gemini 429: RESOURCE_EXHAUSTED")
            return [self._bubble("HI", "Oi")]

        def fake_wait(state, reasons="", interval=600, **kw):
            waits.append(interval)
            state["_progress_hook"]("Cotas de IA esgotadas: tentando de novo em 1 min.")
        msgs = []
        with mock.patch.object(mobile_translator, "call_vision_api", side_effect=fake_vision), \
                mock.patch.object(quota_wait, "wait_for_quota", side_effect=fake_wait):
            res = mobile_translator.translate_manga_folder(
                self.src, progress_cb=lambda st, c, t, m, result=None: msgs.append(m))
        self.assertEqual((res["translated"], res["failed"]), (3, 0))
        self.assertEqual(waits, [60])  # 1ª espera curta
        self.assertTrue(any("Cotas de IA esgotadas" in m for m in msgs))

    def test_skip_option_and_non_quota_errors_do_not_wait(self):
        self.cfg["quota_fallback"] = "skip"

        def fake_vision(b64, cfg, extra_prompt=""):
            raise RuntimeError("Gemini 429: quota exceeded")
        with mock.patch.object(mobile_translator, "call_vision_api", side_effect=fake_vision), \
                mock.patch.object(quota_wait, "wait_for_quota") as w:
            with self.assertRaises(RuntimeError):
                mobile_translator.translate_manga_folder(self.src)
        w.assert_not_called()
        self.assertTrue(mobile_translator.is_quota_error("Groq 429: rate limit"))
        self.assertFalse(mobile_translator.is_quota_error("Gemini bloqueou a página (SAFETY)."))

    def test_defaults(self):
        d = mobile_config.get_default_config()
        self.assertEqual((d["quota_fallback"], d["context_pages"]), ("wait", 2))


if __name__ == "__main__":
    unittest.main()
