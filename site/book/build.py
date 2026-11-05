"""Build the static reader and printable book from one edited manuscript.

Authoring dependencies: ReportLab (PDF) and Pillow (image dimensions).
The published reader has no dependencies or build step.
"""

import html
import json
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph

HERE = Path(__file__).resolve().parent
BOOK = json.loads((HERE / "book.json").read_text(encoding="utf-8"))
PAGES = BOOK["pages"]
PDF_NAME = "where-does-my-picture-go.pdf"


def esc(text):
    return html.escape(str(text), quote=True)


PIP = (
    '<svg class="pip" viewBox="0 0 64 56" aria-hidden="true"><path d="M6 14h52v32a4 4 0 0 1-4 4H10a4 4 0 0 1-4-4z" fill="#3aa89d"/>'
    '<path d="M6 14l26 20 26-20" fill="none" stroke="#1f7d78" stroke-width="3" stroke-linejoin="round"/>'
    '<circle cx="24" cy="30" r="2.6" fill="#1f3444"/><circle cx="40" cy="30" r="2.6" fill="#1f3444"/>'
    '<path d="M26 37q6 5 12 0" fill="none" stroke="#1f3444" stroke-width="2.4" stroke-linecap="round"/>'
    '<path d="M20 50v5M44 50v5" stroke="#1f3444" stroke-width="3" stroke-linecap="round"/></svg>'
)


def picture_tag(page, number, extra_class=""):
    return (
        f'<figure class="picture {extra_class}" data-focus="{esc(page.get("focus", "center"))}">'
        f'<img src="assets/{esc(page["image"])}.jpg" alt="{esc(page["alt"])}" '
        f'width="1536" height="1024" loading="{"eager" if number <= 2 else "lazy"}" decoding="async">'
        "</figure>"
    )


def build_html():
    sections = []
    contents = []
    total = len(PAGES)
    for number, page in enumerate(PAGES, 1):
        kind = page.get("kind", "story-page")
        layout = page.get("layout", "moment")
        tag = "h1" if number == 1 else "h2"
        paragraphs = "".join(f"<p>{esc(text)}</p>" for text in page["text"])
        ask = (
            f'<p class="ask">{PIP}<span>{esc(page["ask"])}</span></p>' if page.get("ask") and kind != "cover" else ""
        )
        activity = ""
        if page.get("activity"):
            activity = (
                '<section class="activity-wrap" aria-label="Try it with Pip">'
                '<h3 class="try-title">Try it with Pip</h3>'
                f'<div class="activity" data-activity="{esc(page["activity"])}"></div></section>'
            )
        print_prompt = f'<p class="print-prompt">{esc(page["print"])}</p>' if page.get("print") else ""
        number_tag = f'<div class="page-number"><span>{number}</span></div>'
        extra = ""
        if kind == "glossary":
            extra = (
                '<dl class="words">'
                + "".join(
                    f"<div><dt>{esc(word)}</dt><dd>{esc(meaning)}</dd></div>"
                    for word, meaning in page["entries"]
                )
                + "</dl>"
            )
        if kind == "sources":
            extra = (
                '<ul class="sources-list">'
                + "".join(
                    f'<li><a href="{esc(source["url"])}">{esc(source["title"])}</a>'
                    f'<p>{esc(source["note"])}</p><span class="source-url">{esc(source["url"])}</span></li>'
                    for source in page["sources"]
                )
                + "</ul>"
            )
        if kind == "drawing":
            extra = '<div class="drawing-space"><span>Make your drawing on a piece of paper.</span></div>'

        title_html = f'<{tag} id="title-{esc(page["id"])}" tabindex="-1">{esc(page["title"])}</{tag}>'
        chapter_html = f'<p class="chapter">{esc(page["chapter"])}</p>'

        if kind == "cover":
            body = (
                f'{picture_tag(page, number, "cover-art")}'
                '<div class="cover-plate">'
                f'{title_html}'
                f'<p class="subtitle">{esc(page["text"][0])}</p>'
                f'<p class="age">{esc(page["ask"])}</p>'
                f'<a class="begin" href="#{esc(PAGES[1]["id"])}">Open the book</a>'
                "</div>"
            )
        elif kind in {"guide", "sources", "glossary", "drawing"}:
            body = (
                f'<div class="page-copy">{chapter_html}{title_html}'
                f'<div class="story">{paragraphs}</div>{extra}{ask}{print_prompt}{number_tag}</div>'
            )
        elif layout == "discover":
            body = (
                f'<div class="side">{picture_tag(page, number)}{activity}</div>'
                f'<div class="page-copy">{chapter_html}{title_html}'
                f'<div class="story">{paragraphs}</div>{ask}{print_prompt}{number_tag}</div>'
            )
        else:
            body = (
                f'{picture_tag(page, number)}'
                f'<div class="page-copy">{chapter_html}{title_html}'
                f'<div class="story">{paragraphs}</div>{ask}{activity}{print_prompt}{number_tag}</div>'
            )
        sections.append(
            f'<article class="page {esc(kind)} layout-{esc(layout)}" id="{esc(page["id"])}" '
            f'data-title="{esc(page["title"])}" aria-labelledby="title-{esc(page["id"])}">{body}</article>'
        )
        thumb = (
            f'<img src="assets/{esc(page["image"])}.jpg" alt="" loading="lazy" decoding="async">'
            if page.get("image")
            else '<span class="thumb-blank" aria-hidden="true"></span>'
        )
        contents.append(
            f'<li><a href="#{esc(page["id"])}">{thumb}<span class="thumb-number">{number}</span>'
            f'<span class="thumb-title">{esc(page["title"])}</span></a></li>'
        )

    output = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="An illustrated read-together book for ages 5–7 about data centers, GPUs, and keeping data safe. Includes playful activities and a printable edition.">
<meta name="theme-color" content="#f6ead3">
<title>{esc(BOOK["title"])}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fredoka:wght@500;600&family=Andika:ital,wght@0,400;0,700;1,400&display=swap">
<link rel="stylesheet" href="book.css">
<link rel="icon" href="data:,">
<script src="book.js" defer></script>
</head>
<body>
<a class="skip" href="#reader">Skip to the book</a>
<header class="topbar">
  <a class="brand" href="#cover">{PIP}<span>Where Does My Picture Go?<small>Read together · Ages 5–7</small></span></a>
  <nav class="tools" aria-label="Book tools">
    <button type="button" id="open-contents" hidden>Pages</button>
    <button type="button" id="read-aloud" aria-pressed="false" hidden>Read aloud</button>
    <a class="button quiet" href="{PDF_NAME}" download>Print book</a>
  </nav>
</header>
<p id="voice-status" class="sr-only" role="status"></p>
<noscript><p class="no-js-note">Scroll to read every page. The printable book and story work without JavaScript.</p></noscript>
<div class="spread">
  <button type="button" id="previous" class="turn turn-back" aria-label="Back one page">‹</button>
  <main class="book" id="reader" aria-label="Children’s picture book">
{"".join(sections)}
  </main>
  <button type="button" id="next" class="turn turn-next" aria-label="Next page">›</button>
</div>
<nav class="navigation" aria-label="Turn the page">
  <button type="button" id="previous-bar">‹ Back</button>
  <div class="progress"><span id="counter" aria-live="polite">Page 1 of {total}</span><progress id="progress" max="{total}" value="1" aria-label="Book progress"></progress></div>
  <button type="button" id="next-bar" class="primary">Next ›</button>
</nav>
<footer class="footnote">
  <p>Read a little. Wonder a lot. <a href="#grownups">For grown-ups</a></p>
  <p><a href="{PDF_NAME}" download>Printable book</a> · <a href="../">Data center walkthrough</a> · <a href="../security.html">Security walkthrough</a></p>
</footer>
<dialog id="contents" aria-labelledby="contents-title">
  <div class="contents-head"><h2 id="contents-title">Choose a page</h2><button type="button" id="close-contents">Close</button></div>
  <ol class="contents-list">{"".join(contents)}</ol>
</dialog>
</body>
</html>
"""
    (HERE / "index.html").write_text(output, encoding="utf-8")


INK = colors.HexColor("#1f3444")
TEAL = colors.HexColor("#1f7d78")
TEAL_2 = colors.HexColor("#3aa89d")
MUTED = colors.HexColor("#5d6b72")
GOLD = colors.HexColor("#e9b949")
CORAL = colors.HexColor("#e26a4f")
LINE = colors.HexColor("#d9c9a6")
PAPER = colors.HexColor("#fbf3e3")
CREAM = colors.HexColor("#fff9ec")
SKY = colors.HexColor("#d9ecef")
WIDTH, HEIGHT = 792, 612  # US Letter landscape; print with Fit for A4.
FOCUS = {"left": 0.18, "center": 0.5, "right": 0.82, "top": 0.5}


def paragraph(pdf, text, x, top, width, size=19, bold=False, color=INK, leading=None):
    """Draw text using a top coordinate; return the next free top coordinate."""
    text = text.replace("–", "-").replace("—", "-").replace("‑", "-")
    style = ParagraphStyle(
        "book",
        fontName="BookBold" if bold else "Book",
        fontSize=size,
        leading=leading or size * 1.4,
        textColor=color,
        alignment=TA_LEFT,
        splitLongWords=True,
        spaceAfter=0,
    )
    block = Paragraph(esc(text), style)
    _, height = block.wrap(width, HEIGHT)
    if top - height < 40:
        raise ValueError(f"Text overflows page near: {text[:65]}")
    block.drawOn(pdf, x, top - height)
    return top - height


def clipped_image(pdf, name, x, y, width, height, radius=0, focus="center", corners=None):
    """Draw an image scaled to cover a box, clipped to that box (optionally rounded).

    Artwork is 3:2. The box decides how much of the long side shows; ``focus`` picks
    which part survives, so a character is never cropped away on purpose.
    """
    path = pdf.beginPath()
    if corners:
        # corners: (top-left, top-right, bottom-right, bottom-left) radii
        tl, tr, br, bl = corners
        path.moveTo(x + tl, y + height)
        path.lineTo(x + width - tr, y + height)
        path.arcTo(x + width - 2 * tr, y + height - 2 * tr, x + width, y + height, 90, -90)
        path.lineTo(x + width, y + br)
        path.arcTo(x + width - 2 * br, y, x + width, y + 2 * br, 0, -90)
        path.lineTo(x + bl, y)
        path.arcTo(x, y, x + 2 * bl, y + 2 * bl, 270, -90)
        path.lineTo(x, y + height - tl)
        path.arcTo(x, y + height - 2 * tl, x + 2 * tl, y + height, 180, -90)
        path.close()
    elif radius:
        path.roundRect(x, y, width, height, radius)
    else:
        path.rect(x, y, width, height)
    pdf.saveState()
    pdf.clipPath(path, stroke=0, fill=0)
    scale = max(width / 1536, height / 1024)
    draw_w, draw_h = 1536 * scale, 1024 * scale
    fx = FOCUS.get(focus, 0.5)
    offset_x = (width - draw_w) * fx
    offset_y = (height - draw_h) * (0.28 if focus == "top" else 0.45)
    pdf.drawImage(str(HERE / "assets" / f"{name}.jpg"), x + offset_x, y + offset_y, draw_w, draw_h)
    pdf.restoreState()
    if radius or corners:
        pdf.setStrokeColor(CREAM)
        pdf.setLineWidth(4)
        pdf.drawPath(path, stroke=1, fill=0)
        pdf.setLineWidth(1)


def pip(pdf, x, y, size=18):
    """A small Pip: teal envelope with a face, drawn with primitives."""
    w, h = size, size * 0.8
    pdf.setFillColor(TEAL_2)
    pdf.roundRect(x, y, w, h, 2, stroke=0, fill=1)
    pdf.setStrokeColor(TEAL)
    pdf.setLineWidth(1.2)
    pdf.line(x, y + h, x + w / 2, y + h * 0.45)
    pdf.line(x + w, y + h, x + w / 2, y + h * 0.45)
    pdf.setFillColor(INK)
    pdf.circle(x + w * 0.35, y + h * 0.35, 1.1, stroke=0, fill=1)
    pdf.circle(x + w * 0.65, y + h * 0.35, 1.1, stroke=0, fill=1)
    pdf.setLineWidth(1)
    pdf.arc(x + w * 0.38, y + h * 0.08, x + w * 0.62, y + h * 0.32, 200, 140)


def ask_box(pdf, text, x, top, width):
    """Pip's question in a dashed cream box; returns the new top."""
    style_h = paragraph_height(text, width - 34, 12.5)
    box_h = style_h + 20
    pdf.setFillColor(CREAM)
    pdf.setStrokeColor(LINE)
    pdf.setDash(4, 3)
    pdf.roundRect(x, top - box_h, width, box_h, 10, stroke=1, fill=1)
    pdf.setDash()
    pip(pdf, x + 9, top - box_h / 2 - 7, 16)
    paragraph(pdf, text, x + 34, top - 10, width - 44, 12.5, color=INK)
    return top - box_h


def paragraph_height(text, width, size):
    style = ParagraphStyle("m", fontName="Book", fontSize=size, leading=size * 1.4)
    _, height = Paragraph(esc(text), style).wrap(width, HEIGHT)
    return height


def page_number(pdf, number):
    pdf.setFillColor(GOLD)
    pdf.circle(WIDTH - 44, 34, 12, stroke=0, fill=1)
    pdf.setFillColor(INK)
    pdf.setFont("BookBold", 9)
    pdf.drawCentredString(WIDTH - 44, 30.5, str(number))
    pdf.setFont("Book", 8)
    pdf.setFillColor(MUTED)
    pdf.drawString(34, 30, BOOK["title"])


def furniture(pdf, page, number):
    pdf.setFillColor(PAPER)
    pdf.rect(0, 0, WIDTH, HEIGHT, stroke=0, fill=1)
    pdf.bookmarkPage(page["id"])
    pdf.addOutlineEntry(page["title"], page["id"], level=0)
    if page.get("kind") != "cover":
        page_number(pdf, number)


def try_box(pdf, page, x, top, width):
    """Paper version of the browser activity: a dashed 'Try it with Pip' box."""
    text = page.get("print") or page.get("ask") or ""
    h = paragraph_height(text, width - 24, 11) + 40
    pdf.setFillColor(CREAM)
    pdf.setStrokeColor(LINE)
    pdf.setDash(4, 3)
    pdf.roundRect(x, top - h, width, h, 12, stroke=1, fill=1)
    pdf.setDash()
    pip(pdf, x + 12, top - 24, 16)
    pdf.setFont("BookBold", 10)
    pdf.setFillColor(TEAL)
    pdf.drawString(x + 34, top - 20, "Try it with Pip")
    paragraph(pdf, text, x + 12, top - 32, width - 24, 11, color=INK)
    return top - h


def story_block(pdf, page, x, top, width, size=18, title_size=27):
    top = paragraph(pdf, page["chapter"], x, top, width, 10, True, TEAL) - 12
    top = paragraph(pdf, page["title"], x, top, width, title_size, True) - 16
    for text in page["text"]:
        top = paragraph(pdf, text, x, top, width, size) - 11
    return top


def build_pdf():
    # ReportLab includes freely redistributable Bitstream Vera fonts.
    import reportlab

    font_dir = Path(reportlab.__file__).parent / "fonts"
    pdfmetrics.registerFont(TTFont("Book", str(font_dir / "Vera.ttf")))
    pdfmetrics.registerFont(TTFont("BookBold", str(font_dir / "VeraBd.ttf")))
    pdfmetrics.registerFontFamily("Book", normal="Book", bold="BookBold")
    pdf = canvas.Canvas(str(HERE / PDF_NAME), pagesize=(WIDTH, HEIGHT), pageCompression=1)
    pdf.setTitle(BOOK["title"])
    pdf.setAuthor("Sentinel Lab")
    pdf.setSubject(
        "A read-together children's book about modern data centers and data security, ages 5-7"
    )
    pdf.setCreator("Sentinel Lab book edition")

    for number, page in enumerate(PAGES, 1):
        furniture(pdf, page, number)
        kind = page.get("kind", "story-page")
        layout = page.get("layout", "moment")
        focus = page.get("focus", "center")
        if kind == "cover":
            clipped_image(pdf, "cover", 0, 200, WIDTH, HEIGHT - 200, focus="top")
            pdf.setFillColor(PAPER)
            pdf.roundRect(-40, 150, WIDTH + 80, 80, 40, stroke=0, fill=1)
            pdf.rect(0, 0, WIDTH, 170, stroke=0, fill=1)
            top = paragraph(pdf, BOOK["title"], 44, 196, 704, 40, True, INK) - 10
            top = paragraph(pdf, page["text"][0], 44, top, 640, 17) - 10
            paragraph(pdf, page["ask"], 44, top, 640, 12, color=MUTED)
        elif kind in {"guide", "glossary", "drawing", "sources"}:
            top = paragraph(pdf, page["chapter"], 40, 573, 712, 10, True, TEAL) - 13
            top = paragraph(pdf, page["title"], 40, top, 712, 27, True) - 18
            if kind == "guide":
                left_top = right_top = top
                for index, text in enumerate(page["text"]):
                    if index < 3:
                        left_top = paragraph(pdf, text, 40, left_top, 335, 13) - 18
                    else:
                        right_top = paragraph(pdf, text, 414, right_top, 335, 13) - 18
                paragraph(
                    pdf,
                    "Printing: 32 landscape pages. Choose Fit on Letter or A4 paper. For a folded booklet, use your printer’s booklet setting. Read-aloud depends on browser/device support; no recording is collected by this book.",
                    414,
                    right_top,
                    335,
                    12,
                    color=MUTED,
                )
            elif kind == "glossary":
                top = paragraph(pdf, page["text"][0], 40, top, 700, 17) - 23
                for index, (word, meaning) in enumerate(page["entries"]):
                    x = 40 if index % 2 == 0 else 414
                    y = top - (index // 2) * 89
                    pdf.setFillColor(CREAM)
                    pdf.setStrokeColor(LINE)
                    pdf.roundRect(x - 8, y - 76, 350, 80, 10, stroke=1, fill=1)
                    bottom = paragraph(pdf, word, x, y - 6, 330, 18, True, TEAL) - 3
                    paragraph(pdf, meaning, x, bottom, 330, 13.5)
            elif kind == "sources":
                top = paragraph(pdf, page["text"][0], 40, top, 700, 13) - 22
                for index, source in enumerate(page["sources"]):
                    x = 40 if index % 2 == 0 else 414
                    y = top - (index // 2) * 183
                    pdf.setStrokeColor(LINE)
                    pdf.setLineWidth(2)
                    pdf.line(x, y, x + 335, y)
                    pdf.setLineWidth(1)
                    bottom = paragraph(pdf, source["title"], x, y - 12, 335, 15, True, TEAL)
                    pdf.linkURL(source["url"], (x, bottom, x + 335, y), relative=0)
                    bottom = paragraph(pdf, source["note"], x, bottom - 9, 335, 12)
                    paragraph(pdf, source["url"], x, bottom - 9, 335, 8.4, color=MUTED)
            else:
                for text in page["text"]:
                    top = paragraph(pdf, text, 40, top, 710, 18) - 7
                if page.get("ask"):
                    top = ask_box(pdf, page["ask"], 40, top - 4, 420) - 6
                top = paragraph(pdf, page["print"], 40, top - 9, 710, 11, color=MUTED) - 20
                pdf.setFillColor(CREAM)
                pdf.setStrokeColor(LINE)
                pdf.setDash(5, 4)
                pdf.roundRect(40, 59, 712, top - 59, 14, stroke=1, fill=1)
                pdf.setDash()
        elif layout == "scene":
            clipped_image(pdf, page["image"], 0, 292, WIDTH, HEIGHT - 292, focus=focus)
            pdf.setFillColor(PAPER)
            pdf.roundRect(-40, 262, WIDTH + 80, 60, 30, stroke=0, fill=1)
            top = story_block(pdf, page, 44, 286, 700, size=17, title_size=25)
            if page.get("ask"):
                ask_box(pdf, page["ask"], 44, top - 2, 480)
        elif layout == "talk":
            clipped_image(pdf, page["image"], 404, 70, 356, 460, focus=focus, corners=(22, 22, 22, 70))
            top = story_block(pdf, page, 40, 556, 338, size=18)
            if page.get("ask"):
                ask_box(pdf, page["ask"], 40, top - 2, 338)
        elif layout == "discover":
            clipped_image(pdf, page["image"], 30, 306, 360, 240, radius=16, focus=focus)
            try_box(pdf, page, 30, 290, 360)
            top = story_block(pdf, page, 412, 556, 340, size=17, title_size=25)
            if page.get("ask"):
                ask_box(pdf, page["ask"], 412, top - 2, 340)
        else:  # moment
            clipped_image(pdf, page["image"], 32, 86, 386, 440, focus=focus, corners=(120, 60, 110, 70))
            top = story_block(pdf, page, 450, 556, 302, size=19)
            if page.get("ask"):
                ask_box(pdf, page["ask"], 450, top - 2, 302)
        pdf.showPage()
    pdf.save()


if __name__ == "__main__":
    assert len(PAGES) == 32, "Keep the print edition at 32 pages."
    assert len({page["id"] for page in PAGES}) == len(PAGES)
    for page in PAGES:
        if page.get("image"):
            assert (HERE / "assets" / f"{page['image']}.jpg").is_file()
    build_html()
    build_pdf()
    print(f"Built {len(PAGES)} HTML pages and {PDF_NAME}")
