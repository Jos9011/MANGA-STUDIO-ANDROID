"""
tests/test_mobile_engine.py - Testes unitários para os módulos Python do Manga Studio Mobile.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import os
import sys
import unittest
from PIL import Image

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app", "src", "main", "python")))

import mobile_config
import mobile_drive_helper
import mobile_typesetter
from mobile_server import app


class MobileEngineTests(unittest.TestCase):

    def test_mobile_config_defaults(self):
        cfg = mobile_config.get_default_config()
        self.assertFalse(cfg["use_local_llm"], "IA local deve ser False no celular")
        self.assertIn("gemini_api_key", cfg)
        self.assertIn("groq_api_key", cfg)
        self.assertIn("max_image_dim", cfg)

    def test_clean_balloon_area(self):
        img_pil = Image.new("RGB", (100, 100), (50, 50, 50))
        cleaned = mobile_typesetter.clean_balloon_area(img_pil, 20, 20, 80, 80)
        self.assertEqual(cleaned.size, (100, 100))
        center_color = cleaned.getpixel((50, 50))
        self.assertEqual(center_color, (255, 255, 255))

    def test_render_dialogue_balloon(self):
        pil_img = Image.new("RGB", (120, 120), (255, 255, 255))
        rendered = mobile_typesetter.render_dialogue_balloon(
            pil_img, "OLÁ MUNDO!", 20, 20, 100, 100
        )
        self.assertIsInstance(rendered, Image.Image)
        self.assertEqual(rendered.size, (120, 120))

    def test_server_health_and_index(self):
        client = app.test_client()
        res = client.get("/api/health")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("status"), "ok")

        idx_res = client.get("/")
        self.assertEqual(idx_res.status_code, 200)
        self.assertIn(b"Manga", idx_res.data)

    def test_drive_folders_and_library(self):
        client = app.test_client()
        d_res = client.get("/api/drive_folders")
        self.assertEqual(d_res.status_code, 200)
        d_data = d_res.get_json()
        self.assertTrue(d_data.get("available"))

        l_res = client.get("/api/library")
        self.assertEqual(l_res.status_code, 200)
        l_data = l_res.get_json()
        self.assertIn("translated", l_data)
        self.assertIn("raw", l_data)

    def test_status_endpoint_ollama_disabled(self):
        client = app.test_client()
        st_res = client.get("/api/status")
        self.assertEqual(st_res.status_code, 200)
        st_data = st_res.get_json()
        self.assertEqual(st_data["ollama"]["status"], "disabled_mobile")
        self.assertIn("gemini", st_data)
        self.assertIn("groq", st_data)

    def test_thumbnail_generation(self):
        tmp_img = os.path.join(mobile_config.get_base_dir(), "test_thumb.jpg")
        try:
            im = Image.new("RGB", (200, 300), color="blue")
            im.save(tmp_img)
            thumb = mobile_drive_helper.generate_thumbnail(tmp_img)
            self.assertIsNotNone(thumb)
            self.assertTrue(os.path.exists(thumb))
        finally:
            if os.path.exists(tmp_img):
                os.remove(tmp_img)


if __name__ == "__main__":
    unittest.main()
