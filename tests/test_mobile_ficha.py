"""
tests/test_mobile_ficha.py - Ficha da Obra + Líder no celular (Fase 1 adaptada à IA Vision).
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

from PIL import Image

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app", "src", "main", "python")))

import ficha_obra
import mobile_config
import mobile_ficha
import mobile_translator
import mobile_vision_api

OBRA = "Toshiue no Kuro Gal Doukyuusei - OLDER BLACK GAL CLASSMATE"
CFG = {"provider": "groq", "groq_api_key": "gsk_teste", "gemini_api_key": "AQ.teste",
       "output_dir": "", "max_image_dim": 400}
LEADER_JSON = json.dumps({"personagens": [
    {"original": "MANABU TOKITO", "pt": "MANABU TOKITO", "genero": "M",
     "nota": "protagonista; Kirara o chama de 'Otaku'"},
    {"original": "KIRARA SAITO", "pt": "Kirara Saito", "genero": "F", "nota": "ex-colega de classe"},
    {"original": "SUNAHAMA", "pt": "Sunahama", "genero": "?", "nota": "possível empresa"},
], "termos": []})


class _Resp:
    def __init__(self, status, data):
        self.status_code, self._data, self.text = status, data, json.dumps(data)

    def json(self):
        return self._data


def _groq_ok(content):
    return _Resp(200, {"choices": [{"message": {"content": content}}]})


class TestPromptAndVision(unittest.TestCase):
    def test_prompt_rules(self):
        self.assertIn('"original"', mobile_vision_api.PROMPT)
        self.assertIn("NUNCA deixe palavras em inglês", mobile_vision_api.PROMPT)

    def test_extra_prompt_reaches_provider_and_old_calls_still_work(self):
        fn = mock.Mock(return_value=[])
        with mock.patch.dict(mobile_vision_api._CALLS, {"groq": (fn, "a", "b")}):
            mobile_vision_api.call_vision_api("b64", CFG)
            self.assertEqual(fn.call_args.kwargs, {})  # sem ficha: chamada igual à de antes
            mobile_vision_api.call_vision_api("b64", CFG, extra_prompt="FICHA DA OBRA X")
            self.assertTrue(fn.call_args.kwargs["prompt"].endswith("FICHA DA OBRA X"))
            self.assertTrue(fn.call_args.kwargs["prompt"].startswith(mobile_vision_api.PROMPT))

    def test_real_provider_functions_send_the_custom_prompt(self):
        sent = []

        def fake_post(url, json=None, **kw):
            sent.append(json)
            if "generativelanguage" in url:
                return _Resp(200, {"candidates": [{"content": {"parts": [{"text": "[]"}]}}]})
            return _groq_ok("[]")

        with mock.patch.object(mobile_vision_api.requests, "post", side_effect=fake_post):
            mobile_vision_api.call_gemini_vision("b64", ["k"], prompt="PROMPT COM FICHA")
            mobile_vision_api.call_groq_vision("b64", ["k"], prompt="PROMPT COM FICHA")
        self.assertEqual(sent[0]["contents"][0]["parts"][0]["text"], "PROMPT COM FICHA")
        self.assertEqual(sent[1]["messages"][0]["content"][0]["text"], "PROMPT COM FICHA")


class TestLeaderTextCall(unittest.TestCase):
    def test_groq_first_with_leader_model_then_gemini(self):
        calls = []

        def fake_post(url, json=None, **kw):
            calls.append((url, json))
            if "groq" in url:
                return _Resp(500, {"error": "fora do ar"})
            return _Resp(200, {"candidates": [{"content": {"parts": [{"text": "{\"ok\": 1}"}]}}]})

        msgs = [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}]
        with mock.patch.object(mobile_ficha.requests, "post", side_effect=fake_post):
            out = mobile_ficha.chat_text(msgs, dict(CFG, lider_model="openai/gpt-oss-120b"))
        self.assertEqual(out, '{"ok": 1}')
        self.assertEqual(calls[0][1]["model"], "openai/gpt-oss-120b")
        self.assertIn("generativelanguage", calls[1][0])
        self.assertEqual(calls[1][1]["systemInstruction"]["parts"][0]["text"], "S")

    def test_all_providers_failing_returns_empty(self):
        with mock.patch.object(mobile_ficha.requests, "post", side_effect=OSError("sem rede")):
            self.assertEqual(mobile_ficha.chat_text([{"role": "user", "content": "x"}], CFG), "")


class TestChapterFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "MANGAS")
        self.caps = []
        for n in (1, 2):
            cap = os.path.join(self.root, f"{OBRA} Ch.{n}")
            os.makedirs(cap)
            Image.new("RGB", (300, 400), "white").save(os.path.join(cap, "01.jpg"))
            self.caps.append(cap)
        self.out = os.path.join(self.tmp, "out")
        self.prompts = []
        self.env = mock.patch.dict(os.environ, {"MANGA_FICHA": ""})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fake_vision(self, b64, cfg, extra_prompt=""):
        self.prompts.append(extra_prompt)
        return [{"box_2d": [100, 100, 300, 600], "original": "MANABU TOKITO", "translation": "Manabu Tokito"},
                {"box_2d": [400, 100, 600, 600], "original": "MORNING, OTAKU. I'M KIRARA SAITO",
                 "translation": "Bom dia, Otaku. Sou a Kirara Saito"}]

    def _translate(self, cap, leader_post):
        with mock.patch.object(mobile_config, "load_config", return_value=dict(CFG)), \
             mock.patch.object(mobile_translator, "call_vision_api", side_effect=self.fake_vision), \
             mock.patch.object(mobile_ficha.requests, "post", side_effect=leader_post):
            return mobile_translator.translate_manga_folder(cap, os.path.join(self.out, os.path.basename(cap)))

    def test_ficha_created_after_chapter_1_and_used_in_chapter_2(self):
        leader_calls = []

        def leader_post(url, json=None, **kw):
            leader_calls.append(json)
            return _groq_ok(LEADER_JSON)

        s1 = self._translate(self.caps[0], leader_post)
        self.assertEqual(s1["translated"], 1)
        self.assertEqual(self.prompts[0], "")  # 1º capítulo: ainda não há ficha
        self.assertEqual(len(leader_calls), 1)
        self.assertIn("MANABU TOKITO", leader_calls[0]["messages"][1]["content"])

        ficha_path = os.path.join(self.root, ".fichas_obra", "toshiue no kuro gal doukyuusei older black gal classmate.json")
        ficha = ficha_obra.load_ficha(ficha_path)
        self.assertEqual(ficha["obra"], OBRA)
        self.assertEqual([p["pt"] for p in ficha["personagens"]], ["Manabu Tokito", "Kirara Saito"])

        self._translate(self.caps[1], leader_post)
        self.assertIn("Manabu Tokito (homem)", self.prompts[1])
        self.assertIn("Kirara Saito (mulher)", self.prompts[1])

    def test_leader_failure_does_not_break_translation(self):
        s = self._translate(self.caps[0], mock.Mock(side_effect=OSError("sem rede")))
        self.assertEqual((s["translated"], s["failed"]), (1, 0))
        self.assertTrue(os.path.exists(s["cbz"]))

    def test_disabled_ficha_changes_nothing(self):
        with mock.patch.dict(os.environ, {"MANGA_FICHA": "0"}):
            post = mock.Mock(return_value=_groq_ok(LEADER_JSON))
            self._translate(self.caps[0], post)
        post.assert_not_called()
        self.assertFalse(os.path.exists(os.path.join(self.root, ".fichas_obra")))


class TestSharedModulesInSync(unittest.TestCase):
    def test_same_files_as_pc_repo_when_available(self):
        pc = os.environ.get("MANGA_PC_REPO", "")
        if not pc or not os.path.isdir(pc):
            self.skipTest("defina MANGA_PC_REPO para comparar com o repositório do PC")
        here = os.path.join(os.path.dirname(__file__), "..", "app", "src", "main", "python")
        for name in ("ficha_obra.py", "ficha_caminho.py", "lider_capitulo.py"):
            with open(os.path.join(pc, name), encoding="utf-8") as a, open(os.path.join(here, name), encoding="utf-8") as b:
                self.assertEqual(a.read(), b.read(), name)


if __name__ == "__main__":
    unittest.main()
