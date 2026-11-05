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


def build_html():
    sections = []
    contents = []
    for number, page in enumerate(PAGES, 1):
        kind = page.get("kind", "story-page")
        tag = "h1" if number == 1 else "h2"
        picture = ""
        if page.get("image") and kind not in {"guide", "glossary", "drawing"}:
            picture = (
                '<figure class="picture">'
                f'<img src="assets/{esc(page["image"])}.jpg" '
                f'alt="{esc(page["alt"])}" width="1536" height="1024" '
                f'loading="{"eager" if number == 1 else "lazy"}" decoding="async">'
                "</figure>"
            )
        paragraphs = "".join(f"<p>{esc(text)}</p>" for text in page["text"])
        ask = f'<p class="ask">{esc(page["ask"])}</p>' if page.get("ask") else ""
        activity = ""
        if page.get("activity"):
            activity = f'<div class="activity" data-activity="{esc(page["activity"])}" aria-label="Try this page’s activity"></div>'
        print_prompt = (
            f'<p class="print-prompt">{esc(page["print"])}</p>' if page.get("print") else ""
        )
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
            extra = '<div class="drawing-space">Make your drawing on a piece of paper.</div>'
        sections.append(
            f'<article class="page {esc(kind)}" id="{esc(page["id"])}" '
            f'data-title="{esc(page["title"])}" aria-labelledby="title-{esc(page["id"])}">'
            f'{picture}<div class="page-copy"><p class="chapter">{esc(page["chapter"])}</p>'
            f'<{tag} id="title-{esc(page["id"])}" tabindex="-1">{esc(page["title"])}</{tag}>'
            f'<div class="story">{paragraphs}</div>{extra}{ask}{activity}{print_prompt}'
            f'<div class="page-number">{number:02d} / {len(PAGES)}</div></div></article>'
        )
        contents.append(
            f'<li><a href="#{esc(page["id"])}"><span>{number:02d}</span> {esc(page["title"])}</a></li>'
        )

    output = f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="An illustrated read-together book for ages 5–7 about data centers, GPUs, and keeping data safe. Includes playful activities and a printable edition.">
<meta name="theme-color" content="#e9f1e8">
<title>{esc(BOOK["title"])}</title>
<link rel="stylesheet" href="book.css">
<link rel="icon" href="data:,">
<script src="book.js" defer></script>
</head>
<body>
<a class="skip" href="#reader">Skip to the book</a>
<header class="topbar">
  <a class="brand" href="#cover">Where Does My Picture Go?<small>Read together · Ages 5–7</small></a>
  <nav class="tools" aria-label="Book tools">
    <button type="button" id="open-contents" hidden>All pages</button>
    <button type="button" id="read-aloud" aria-pressed="false" hidden>Read aloud</button>
    <a class="button" href="{PDF_NAME}" download>Print book (PDF)</a>
  </nav>
</header>
<p id="voice-status" class="sr-only" role="status"></p>
<noscript><p class="no-js-note">Scroll to read every page. The printable book and story work without JavaScript.</p></noscript>
<main class="book" id="reader" aria-label="Children’s picture book">
{"".join(sections)}
</main>
<nav class="navigation" aria-label="Turn the page">
  <button type="button" id="previous">← Back</button>
  <div class="progress"><span id="counter" aria-live="polite">Page 1 of {len(PAGES)}</span><progress id="progress" max="{len(PAGES)}" value="1" aria-label="Book progress"></progress></div>
  <button type="button" id="next" class="primary">Next →</button>
</nav>
<footer class="footnote">
  <p>Read a little. Wonder a lot. <a href="#grownups">For grown-ups</a></p>
  <p><a href="../">Data center walkthrough</a> · <a href="../security.html">Security walkthrough</a></p>
</footer>
<dialog id="contents" aria-labelledby="contents-title">
  <div class="contents-head"><h2 id="contents-title">Choose a page</h2><button type="button" id="close-contents">Close</button></div>
  <ol class="contents-list">{"".join(contents)}</ol>
</dialog>
</body>
</html>
'''
    (HERE / "index.html").write_text(output, encoding="utf-8")


INK = colors.HexColor("#233a40")
TEAL = colors.HexColor("#17675e")
MUTED = colors.HexColor("#586a69")
GOLD = colors.HexColor("#e8b84e")
LINE = colors.HexColor("#cbd4c6")
PAPER = colors.HexColor("#fffcf5")
WIDTH, HEIGHT = 792, 612  # US Letter landscape; print with Fit for A4.


def paragraph(pdf, text, x, top, width, size=19, bold=False, color=INK, leading=None):
    """Draw text using a top coordinate; return the next free top coordinate."""
    text = text.replace("–", "-").replace("—", "-").replace("‑", "-")
    style = ParagraphStyle(
        "book",
        fontName="BookBold" if bold else "Book",
        fontSize=size,
        leading=leading or size * 1.38,
        textColor=color,
        alignment=TA_LEFT,
        splitLongWords=True,
        spaceAfter=0,
    )
    block = Paragraph(esc(text), style)
    _, height = block.wrap(width, HEIGHT)
    if top - height < 42:
        raise ValueError(f"Text overflows page near: {text[:65]}")
    block.drawOn(pdf, x, top - height)
    return top - height


def image(pdf, name, x, y, width):
    pdf.drawImage(str(HERE / "assets" / f"{name}.jpg"), x, y, width, width * 2 / 3, mask="auto")


def furniture(pdf, page, number):
    pdf.setFillColor(colors.white)
    pdf.rect(0, 0, WIDTH, HEIGHT, stroke=0, fill=1)
    pdf.bookmarkPage(page["id"])
    pdf.addOutlineEntry(page["title"], page["id"], level=0)
    pdf.setStrokeColor(LINE)
    pdf.line(34, 35, WIDTH - 34, 35)
    pdf.setFont("Book", 8)
    pdf.setFillColor(MUTED)
    pdf.drawString(34, 21, BOOK["title"])
    pdf.drawRightString(WIDTH - 34, 21, f"{number:02d} / {len(PAGES)}")


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
        if kind == "cover":
            paragraph(pdf, BOOK["title"], 38, 575, 716, 34, True, TEAL)
            paragraph(pdf, page["text"][0], 40, 520, 700, 16)
            image(pdf, "cover", 132, 105, 528)
            paragraph(pdf, "A read-together book for ages 5-7", 40, 76, 700, 13, color=MUTED)
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
                right_top = paragraph(
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
                    bottom = paragraph(pdf, word, x, y, 330, 19, True, TEAL) - 4
                    paragraph(pdf, meaning, x, bottom, 330, 15)
            elif kind == "sources":
                top = paragraph(pdf, page["text"][0], 40, top, 700, 13) - 22
                for index, source in enumerate(page["sources"]):
                    x = 40 if index % 2 == 0 else 414
                    y = top - (index // 2) * 183
                    pdf.setStrokeColor(LINE)
                    pdf.line(x, y, x + 335, y)
                    bottom = paragraph(pdf, source["title"], x, y - 12, 335, 15, True, TEAL)
                    pdf.linkURL(source["url"], (x, bottom, x + 335, y), relative=0)
                    bottom = paragraph(pdf, source["note"], x, bottom - 9, 335, 12)
                    paragraph(pdf, source["url"], x, bottom - 9, 335, 8.4, color=MUTED)
            else:
                for text in page["text"]:
                    top = paragraph(pdf, text, 40, top, 710, 18) - 7
                top = paragraph(pdf, page["print"], 40, top - 9, 710, 11, color=MUTED) - 20
                pdf.setStrokeColor(LINE)
                pdf.setDash(5, 4)
                pdf.roundRect(40, 59, 712, top - 59, 12, stroke=1, fill=0)
                pdf.setDash()
        else:
            image(pdf, page["image"], 28, 174, 389)
            # The artwork remains unobstructed; the entire story is selectable text.
            x, width = 445, 307
            top = paragraph(pdf, page["chapter"], x, 563, width, 9, True, TEAL) - 14
            top = paragraph(pdf, page["title"], x, top, width, 27, True) - 20
            for text in page["text"]:
                top = paragraph(pdf, text, x, top, width, 19) - 12
            if page.get("ask"):
                top -= 7
                pdf.setStrokeColor(GOLD)
                pdf.setLineWidth(3)
                pdf.line(x, top, x + 32, top)
                pdf.setLineWidth(1)
                top = paragraph(pdf, page["ask"], x, top - 13, width, 12.5, color=TEAL) - 10
            if page.get("print"):
                paragraph(pdf, page["print"], 37, 136, 368, 12, color=MUTED)
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
