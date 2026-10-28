import base64
from io import BytesIO
from pathlib import Path
import string

from flask import Flask, render_template, request
from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024

CHARACTERS = (
    string.ascii_lowercase
    + string.ascii_uppercase
    + string.digits
    + ".,!?'-:;()"
    + "$&"
)
SHEET_COLUMNS = 8
CELL_WIDTH = 120
CELL_HEIGHT = 130
SHEET_WIDTH = SHEET_COLUMNS * CELL_WIDTH
SHEET_ROWS = (len(CHARACTERS) + SHEET_COLUMNS - 1) // SHEET_COLUMNS
SHEET_HEIGHT = SHEET_ROWS * CELL_HEIGHT
MAX_IMAGE_PIXELS = 20_000_000
MAX_TEXT_LENGTH = 2_000
INK_THRESHOLD = 175
MAX_CELL_INK_RATIO = 0.4
MAX_SHEET_ASPECT_RATIO_ERROR = 0.2


def create_character_sheet():
    sheet = Image.new("RGB", (SHEET_WIDTH, SHEET_HEIGHT), "white")
    draw = ImageDraw.Draw(sheet)
    label_font = ImageFont.load_default()

    for index, character in enumerate(CHARACTERS):
        x = (index % SHEET_COLUMNS) * CELL_WIDTH
        y = (index // SHEET_COLUMNS) * CELL_HEIGHT
        draw.rectangle(
            (x, y, x + CELL_WIDTH - 1, y + CELL_HEIGHT - 1),
            outline="#999999",
            width=1,
        )
        draw.text((x + 7, y + 5), f"Write: {character}", fill="#777777", font=label_font)
        draw.line(
            (x + 6, y + 108, x + CELL_WIDTH - 7, y + 108),
            fill="#dddddd",
            width=1,
        )

    return sheet


def create_demo_character_sheet():
    sheet = create_character_sheet()
    font_paths = (
        Path("C:/Windows/Fonts/segoepr.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"),
    )
    font_path = next((path for path in font_paths if path.is_file()), None)
    font = (
        ImageFont.truetype(str(font_path), 42)
        if font_path
        else ImageFont.load_default(size=42)
    )
    draw = ImageDraw.Draw(sheet)
    for index, character in enumerate(CHARACTERS):
        x = (index % SHEET_COLUMNS) * CELL_WIDTH
        y = (index // SHEET_COLUMNS) * CELL_HEIGHT
        bounds = draw.textbbox((0, 0), character, font=font)
        glyph_width = bounds[2] - bounds[0]
        glyph_height = bounds[3] - bounds[1]
        draw.text(
            (
                x + (CELL_WIDTH - glyph_width) / 2 - bounds[0],
                y + 66 - glyph_height / 2 - bounds[1],
            ),
            character,
            fill="#202020",
            font=font,
        )

    return sheet


def load_uploaded_image(upload):
    try:
        image = Image.open(upload.stream)
        if image.format not in {"PNG", "JPEG", "WEBP"}:
            raise ValueError("Upload a PNG, JPEG, or WEBP image.")
        if image.width * image.height > MAX_IMAGE_PIXELS:
            raise ValueError("The uploaded image is too large to process.")
        image.load()
        image = ImageOps.exif_transpose(image)
        expected_aspect_ratio = SHEET_WIDTH / SHEET_HEIGHT
        image_aspect_ratio = image.width / image.height
        if abs(image_aspect_ratio / expected_aspect_ratio - 1) > MAX_SHEET_ASPECT_RATIO_ERROR:
            raise ValueError(
                "This image is not the Inkprint character sheet. Upload a scan or photo "
                "of the completed character sheet; handwritten paragraphs and screenshots "
                "aren't supported by this prototype yet."
            )
        image = image.convert("RGBA")
        background = Image.new("RGBA", image.size, "white")
        image = Image.alpha_composite(background, image).convert("RGB")
        return image.resize((SHEET_WIDTH, SHEET_HEIGHT))
    except UnidentifiedImageError as exc:
        raise ValueError("The uploaded file is not a readable image.") from exc


def extract_glyphs(sheet):
    grayscale = sheet.convert("L")
    glyphs = {}

    for index, character in enumerate(CHARACTERS):
        x = (index % SHEET_COLUMNS) * CELL_WIDTH
        y = (index // SHEET_COLUMNS) * CELL_HEIGHT
        writing_area = grayscale.crop(
            (x + 7, y + 29, x + CELL_WIDTH - 7, y + 102)
        )
        mask = writing_area.point(
            lambda pixel: 0 if pixel < INK_THRESHOLD else 255,
            mode="L",
        )
        ink_ratio = mask.histogram()[0] / (mask.width * mask.height)
        if ink_ratio > MAX_CELL_INK_RATIO:
            continue
        bounds = mask.point(lambda pixel: 255 if pixel == 0 else 0).getbbox()
        if bounds is None:
            continue

        glyph = mask.crop(bounds)
        if glyph.width < 2 or glyph.height < 3:
            continue

        glyph.thumbnail((74, 58), Image.Resampling.LANCZOS)
        glyphs[character] = glyph

    return glyphs


def character_width(character, glyphs):
    return 22 if character == " " else glyphs[character].width + 5


def line_width(line, glyphs):
    return sum(character_width(character, glyphs) for character in line)


def wrap_text(text, glyphs, max_width=1_096):
    lines = []
    for source_line in text.splitlines() or [""]:
        words = source_line.split()
        line = ""
        for word in words:
            candidate = f"{line} {word}".strip()
            if line and line_width(candidate, glyphs) > max_width:
                if line:
                    lines.append(line)
                line = ""

            while line_width(word, glyphs) > max_width:
                split_at = 1
                while (
                    split_at < len(word)
                    and line_width(word[: split_at + 1], glyphs) <= max_width
                ):
                    split_at += 1
                lines.append(word[:split_at])
                word = word[split_at:]
            line = f"{line} {word}".strip()
        lines.append(line)
    return lines


def render_handwriting(text, glyphs):
    lines = wrap_text(text, glyphs)
    line_height = 100
    margin = 72
    image = Image.new("RGB", (1_240, max(1, len(lines)) * line_height + margin * 2), "white")
    draw = ImageDraw.Draw(image)

    for line_index, line in enumerate(lines):
        x = margin
        baseline = margin + line_index * line_height + 76
        for character in line:
            if character == " ":
                x += 22
                continue
            glyph = glyphs[character]
            image.paste(
                (31, 35, 30),
                (x, baseline - glyph.height),
                ImageOps.invert(glyph),
            )
            x += glyph.width + 5

    return image


def create_pdf_pages(image):
    line_height = 100
    margin = 72
    page_height = 1_754
    lines_per_page = (page_height - margin * 2) // line_height
    line_count = max(1, (image.height - margin * 2) // line_height)
    pages = []

    for first_line in range(0, line_count, lines_per_page):
        last_line = min(first_line + lines_per_page, line_count)
        source_top = 0 if first_line == 0 else margin + first_line * line_height
        source_bottom = margin + last_line * line_height
        page = Image.new("RGB", (image.width, page_height), "white")
        page.paste(
            image.crop((0, source_top, image.width, source_bottom)),
            (0, 0 if first_line == 0 else margin),
        )
        pages.append(page)

    return pages


def image_bytes(image, format_name):
    buffer = BytesIO()
    if format_name == "PDF":
        pages = create_pdf_pages(image)
        pages[0].save(
            buffer,
            format="PDF",
            resolution=150,
            save_all=True,
            append_images=pages[1:],
        )
    else:
        image.save(buffer, format=format_name)
    return buffer.getvalue()


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/character-sheet.png")
def character_sheet():
    return app.response_class(
        image_bytes(create_character_sheet(), "PNG"),
        mimetype="image/png",
        headers={"Content-Disposition": 'attachment; filename="handwriting-sheet.png"'},
    )


@app.get("/sample-handwriting.png")
def sample_handwriting():
    return app.response_class(
        image_bytes(create_demo_character_sheet(), "PNG"),
        mimetype="image/png",
        headers={"Content-Disposition": 'attachment; filename="demo-handwriting-sheet.png"'},
    )


@app.post("/generate")
def generate():
    text = request.form.get("text", "")
    upload = request.files.get("sample")

    if not text.strip():
        return render_template("index.html", error="Enter the text you want to render."), 400
    if len(text) > MAX_TEXT_LENGTH:
        return render_template(
            "index.html",
            error=f"Text must be {MAX_TEXT_LENGTH:,} characters or fewer.",
        ), 400
    text = text.replace("\t", "    ").replace("\r", "")
    if upload is None or not upload.filename:
        return render_template("index.html", error="Choose your completed handwriting sheet."), 400

    try:
        sample = load_uploaded_image(upload)
        glyphs = extract_glyphs(sample)
        unsupported = sorted(set(text) - set(CHARACTERS) - {" ", "\n", "\r", "\t"})
        missing = sorted(set(text) - set(glyphs) - {" ", "\n", "\r", "\t"})
        if unsupported:
            return render_template(
                "index.html",
                error="Unsupported characters: " + ", ".join(repr(char) for char in unsupported),
            ), 400
        if missing:
            return render_template(
                "index.html",
                error="No handwriting was detected for: "
                + ", ".join(repr(char) for char in missing)
                + ". Fill in those cells and upload the original sheet again. "
                "Use dark ink on white paper, and scan the sheet flat and straight.",
            ), 400

        rendered = render_handwriting(text, glyphs)
        png_data = base64.b64encode(image_bytes(rendered, "PNG")).decode("ascii")
        pdf_data = base64.b64encode(image_bytes(rendered, "PDF")).decode("ascii")
        return render_template(
            "result.html",
            image_data=png_data,
            pdf_data=pdf_data,
        )
    except (OSError, ValueError) as exc:
        return render_template("index.html", error=str(exc)), 400


@app.errorhandler(413)
def request_too_large(_error):
    return render_template(
        "index.html",
        error="The upload is too large. Choose an image smaller than 8 MB.",
    ), 413


if __name__ == "__main__":
    app.run(debug=False)
