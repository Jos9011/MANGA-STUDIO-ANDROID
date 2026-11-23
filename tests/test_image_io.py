"""
tests/test_image_io.py - Regressão do erro "cannot identify image file" no APK
Simula o Pillow do Chaquopy sem codec (WebP/AVIF) e o fallback para o decodificador nativo do Android.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import io
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock
from PIL import Image

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app", "src", "main", "python")))

import mobile_config
import mobile_image_io
import mobile_translator

# Bytes que nenhum Pillow reconhece: representam uma página que o Pillow do APK não decodifica
UNREADABLE = b"\x00\x00\x00\x1cftypavif" + b"\x00" * 64


def _jpeg_bytes(size=(120, 180)):
    buf = io.BytesIO()
    Image.new("RGB", size, (200, 200, 200)).save(buf, "JPEG")
    return buf.getvalue()


class ImageIOTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, name, data):
        p = os.path.join(self.tmp, name)
        with open(p, "wb") as f:
            f.write(data)
        return p

    def test_falls_back_to_android_decoder_when_pillow_cannot_identify(self):
        page = self._write("001.webp", UNREADABLE)
        with mock.patch.object(mobile_image_io, "_android_decode_to_bytes", return_value=_jpeg_bytes()) as native:
            im = mobile_image_io.open_rgb(page)
        native.assert_called_once_with(page)
        self.assertEqual((im.mode, im.size), ("RGB", (120, 180)))

    def test_clear_error_with_real_format_when_nothing_can_decode(self):
        page = self._write("002.jpg", UNREADABLE)
        with mock.patch.object(mobile_image_io, "_android_decode_to_bytes", return_value=None):
            with self.assertRaises(ValueError) as ctx:
                mobile_image_io.open_rgb(page)
        msg = str(ctx.exception)
        self.assertIn("002.jpg", msg)
        self.assertIn("AVIF", msg)

    def test_sniff_format_detects_disguised_and_broken_files(self):
        self.assertEqual(mobile_image_io.sniff_format(self._write("a.jpg", b"RIFF\x10\x00\x00\x00WEBPVP8 ")), "WebP")
        self.assertEqual(mobile_image_io.sniff_format(self._write("b.jpg", b"")), "arquivo vazio (0 bytes)")
        self.assertIn("HTML", mobile_image_io.sniff_format(self._write("c.jpg", b"<!DOCTYPE html><html>")))
        self.assertEqual(mobile_image_io.sniff_format(self._write("d.png", b"\x00\x00\x00\x18ftypheic")), "HEIC/HEIF")

    def test_android_decoder_absent_outside_chaquopy(self):
        self.assertIsNone(mobile_image_io._android_decode_to_bytes(self._write("e.webp", UNREADABLE)))

    def test_transparent_png_flattened_on_white(self):
        p = os.path.join(self.tmp, "t.png")
        Image.new("RGBA", (4, 4), (0, 0, 0, 0)).save(p)
        self.assertEqual(mobile_image_io.open_rgb(p).getpixel((0, 0)), (255, 255, 255))

    def test_translation_succeeds_on_page_pillow_cannot_read(self):
        in_dir = os.path.join(self.tmp, "in")
        os.makedirs(in_dir)
        self._write(os.path.join("in", "001.webp"), UNREADABLE)
        cfg = dict(mobile_config.get_default_config(), gemini_api_key="gm-test")
        with mock.patch.object(mobile_config, "load_config", return_value=cfg), \
             mock.patch.object(mobile_image_io, "_android_decode_to_bytes", return_value=_jpeg_bytes()), \
             mock.patch.object(mobile_translator, "call_vision_api", return_value=[]):
            summary = mobile_translator.translate_manga_folder(in_dir, os.path.join(self.tmp, "out"))
        self.assertEqual((summary["translated"], summary["failed"]), (1, 0))
        with Image.open(os.path.join(self.tmp, "out", "001.jpg")) as out:
            self.assertEqual(out.size, (120, 180))


if __name__ == "__main__":
    unittest.main()
