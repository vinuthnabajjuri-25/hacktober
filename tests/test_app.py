import base64
import io
import re
import unittest
from types import SimpleNamespace

from PIL import Image, ImageDraw, ImageOps

import app


class HandwritingAppTests(unittest.TestCase):
    def setUp(self):
        app.app.config.update(TESTING=True)
        self.client = app.app.test_client()

    def test_home_page_loads(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Download handwriting sheet", response.data)

    def test_character_sheet_download(self):
        response = self.client.get("/character-sheet.png")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "image/png")
        with Image.open(io.BytesIO(response.data)) as sheet:
            self.assertEqual(sheet.size, (app.SHEET_WIDTH, app.SHEET_HEIGHT))

    def test_demo_sheet_download_contains_all_supported_glyphs(self):
        response = self.client.get("/sample-handwriting.png")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "image/png")
        with Image.open(io.BytesIO(response.data)) as sheet:
            glyphs = app.extract_glyphs(sheet)
        self.assertEqual(set(glyphs), set(app.CHARACTERS))
        self.assertIn("$", glyphs)
        self.assertIn("&", glyphs)

    def test_transparent_sample_is_composited_onto_white(self):
        sample = Image.new("RGBA", (app.SHEET_WIDTH, app.SHEET_HEIGHT), (0, 0, 0, 0))
        draw = ImageDraw.Draw(sample)
        draw.line((40, 40, 80, 90), fill="black", width=5)
        buffer = io.BytesIO()
        sample.save(buffer, format="PNG")
        buffer.seek(0)

        loaded = app.load_uploaded_image(SimpleNamespace(stream=buffer))

        self.assertEqual(loaded.getpixel((0, 0)), (255, 255, 255))
        self.assertEqual(loaded.getpixel((60, 65)), (0, 0, 0))

    def test_arbitrary_handwriting_photo_is_rejected_with_clear_error(self):
        sample = Image.new("RGB", (722, 1600), "white")
        buffer = io.BytesIO()
        sample.save(buffer, format="JPEG")
        buffer.seek(0)

        with self.assertRaisesRegex(ValueError, "is not the Inkprint character sheet"):
            app.load_uploaded_image(SimpleNamespace(stream=buffer))

    def test_inverted_sheet_does_not_produce_filled_cell_glyphs(self):
        sample = ImageOps.invert(app.create_character_sheet())

        self.assertEqual(app.extract_glyphs(sample), {})

    def test_generate_returns_preview_and_downloads(self):
        sample = app.create_character_sheet()
        index = app.CHARACTERS.index("A")
        x = (index % app.SHEET_COLUMNS) * app.CELL_WIDTH
        y = (index // app.SHEET_COLUMNS) * app.CELL_HEIGHT
        draw = ImageDraw.Draw(sample)
        draw.line((x + 43, y + 96, x + 60, y + 42), fill="black", width=5)
        draw.line((x + 60, y + 42, x + 77, y + 96), fill="black", width=5)
        draw.line((x + 50, y + 75, x + 70, y + 75), fill="black", width=5)
        buffer = io.BytesIO()
        sample.save(buffer, format="PNG")
        buffer.seek(0)

        response = self.client.post(
            "/generate",
            data={
                "text": "A",
                "sample": (buffer, "sample.png"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)
        png_match = re.search(rb"data:image/png;base64,([A-Za-z0-9+/=]+)", response.data)
        pdf_match = re.search(rb"data:application/pdf;base64,([A-Za-z0-9+/=]+)", response.data)
        self.assertIsNotNone(png_match)
        self.assertIsNotNone(pdf_match)
        png_data = base64.b64decode(png_match.group(1))
        self.assertTrue(png_data.startswith(b"\x89PNG"))
        self.assertTrue(base64.b64decode(pdf_match.group(1)).startswith(b"%PDF"))
        with Image.open(io.BytesIO(png_data)) as preview:
            self.assertEqual(preview.getpixel((72, 72)), (255, 255, 255))

    def test_long_pdf_output_is_split_into_pages(self):
        image = Image.new("RGB", (1_240, 72 + 17 * 100 + 72), "white")
        self.assertEqual(len(app.create_pdf_pages(image)), 2)

    def test_generate_rejects_missing_glyph(self):
        sample = app.create_character_sheet()
        buffer = io.BytesIO()
        sample.save(buffer, format="PNG")
        buffer.seek(0)

        response = self.client.post(
            "/generate",
            data={"text": "A", "sample": (buffer, "blank.png")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"No handwriting was detected", response.data)


if __name__ == "__main__":
    unittest.main()
