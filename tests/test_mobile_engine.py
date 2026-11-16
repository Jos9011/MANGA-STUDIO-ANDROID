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

    def test_server_health_and_endpoints(self):
        client = app.test_client()
        res = client.get("/api/health")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("status"), "ok")

        cfg_res = client.get("/api/config")
        self.assertEqual(cfg_res.status_code, 200)
        cfg_data = cfg_res.get_json()
        self.assertFalse(cfg_data.get("use_local_llm"))


if __name__ == "__main__":
    unittest.main()
