"""Writing the annual report to a PDF file (issue #242, parent #239): a title page, then the reports' sections as
tables, A4 portrait, the long ones continuing on the next page under a repeated header, with a disclaimer in every
page's footer. Amounts and dates are formatted as on screen; the text is set in DejaVu Sans, bundled in
``ui/assets/fonts``, because the PDF base fonts lack the Polish letters.
"""

import io
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import BaseDocTemplate, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.platypus.flowables import Flowable

from financial_app.domain.formatting import format_date, format_number, format_percent, format_quantity
from financial_app.domain.report import Cell, Percent, Report, Section

DISCLAIMER = "Zestawienie pomocnicze, nie jest zeznaniem podatkowym."
FONT = "KapitaSans"
FONT_BOLD = "KapitaSans-Bold"
FONTS = Path(__file__).resolve().parents[1] / "ui" / "assets" / "fonts"
# A column with this header holds a quantity, shown with only the decimals it has
_QUANTITY_HEADER = "Liczba"
_MARGIN = 15 * mm
_MUTED = colors.HexColor("#666666")
_RULE = colors.HexColor("#bbbbbb")
_HEAD = colors.HexColor("#eeeeee")

_BODY = ParagraphStyle("body", fontName=FONT, fontSize=9, leading=12)
_NOTE = ParagraphStyle("note", parent=_BODY, fontSize=8, leading=10, textColor=_MUTED, spaceBefore=3)
_TITLE = ParagraphStyle("title", parent=_BODY, fontName=FONT_BOLD, fontSize=28, leading=34, alignment=TA_CENTER)
_SUBTITLE = ParagraphStyle("subtitle", parent=_BODY, fontSize=16, leading=22, alignment=TA_CENTER)
_DATE = ParagraphStyle("date", parent=_BODY, textColor=_MUTED, alignment=TA_CENTER)
_H1 = ParagraphStyle("h1", parent=_BODY, fontName=FONT_BOLD, fontSize=15, leading=19, spaceBefore=10, spaceAfter=4)
_H2 = ParagraphStyle("h2", parent=_BODY, fontName=FONT_BOLD, fontSize=11, leading=14, spaceBefore=8, spaceAfter=3)
_CELL = ParagraphStyle("cell", parent=_BODY, fontSize=7, leading=8.5)
_CELL_RIGHT = ParagraphStyle("cell-right", parent=_CELL, alignment=TA_RIGHT)
_HEAD_CELL = ParagraphStyle("head-cell", parent=_CELL, fontName=FONT_BOLD)
_HEAD_CELL_RIGHT = ParagraphStyle("head-cell-right", parent=_HEAD_CELL, alignment=TA_RIGHT)

# The heading of each report in the annual report, by the report's name
_HEADINGS = {
    "wyniki": "Wyniki roku",
    "portfolio": "Portfolio na koniec roku",
    "podsumowanie-sprzedazy": "Sprzedaże (FIFO)",
    "dochod-pasywny": "Dochód pasywny",
}


def annual_report_to_pdf(scope: str, year: int, generated: date, reports: Sequence[Report]) -> bytes:
    """The PDF of ``reports`` (in the order given) for the View Scope called ``scope``, generated on ``generated``."""
    _register_fonts()
    buffer = io.BytesIO()
    title = f"Raport roczny {year} · {scope}"
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=_MARGIN,
        rightMargin=_MARGIN,
        topMargin=_MARGIN,
        bottomMargin=_MARGIN + 5 * mm,
        title=title,
        author="KAPITA",
    )
    story: list[Flowable] = [
        Spacer(1, 70 * mm),
        Paragraph(f"Raport roczny {year}", _TITLE),
        Spacer(1, 8 * mm),
        Paragraph(escape(scope), _SUBTITLE),
        Spacer(1, 12 * mm),
        Paragraph(f"Wygenerowano {format_date(generated)}", _DATE),
        PageBreak(),
    ]
    for report in reports:
        story.extend(_report_flowables(report, document.width))
    document.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()


def _register_fonts() -> None:
    if FONT not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(FONT, str(FONTS / "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont(FONT_BOLD, str(FONTS / "DejaVuSans-Bold.ttf")))
        pdfmetrics.registerFontFamily(FONT, normal=FONT, bold=FONT_BOLD, italic=FONT, boldItalic=FONT_BOLD)


def _footer(canvas: Canvas, document: BaseDocTemplate) -> None:
    canvas.saveState()
    canvas.setFont(FONT, 7)
    canvas.setFillColor(_MUTED)
    canvas.drawString(_MARGIN, 10 * mm, DISCLAIMER)
    canvas.drawRightString(A4[0] - _MARGIN, 10 * mm, f"Strona {document.page}")
    canvas.restoreState()


def _report_flowables(report: Report, width: float) -> list[Flowable]:
    flowables: list[Flowable] = [Paragraph(escape(_HEADINGS.get(report.name, report.title)), _H1)]
    flowables.append(Paragraph(escape(report.title), _NOTE))
    flowables.extend(Paragraph(escape(note), _BODY) for note in report.notes)
    for section in report.sections:
        flowables.append(Paragraph(escape(section.title), _H2))
        flowables.append(_table(section, width))
        flowables.extend(Paragraph(escape(note), _NOTE) for note in section.notes)
    return flowables


def _table(section: Section, width: float) -> Table:
    numeric = [_is_numeric(section, column) for column in range(len(section.headers))]
    head = [
        Paragraph(escape(h), _HEAD_CELL_RIGHT if n else _HEAD_CELL)
        for h, n in zip(section.headers, numeric, strict=True)
    ]
    body = [
        [
            Paragraph(escape(_text(cell, header)), _CELL_RIGHT if n else _CELL)
            for cell, header, n in zip(row, section.headers, numeric, strict=True)
        ]
        for row in section.rows
    ]
    table = Table([head, *body], colWidths=_widths(section, width), repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (-1, 0), _HEAD),
                ("LINEBELOW", (0, 0), (-1, -1), 0.25, _RULE),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    return table


def _is_numeric(section: Section, column: int) -> bool:
    values = [row[column] for row in section.rows if row[column] is not None]
    return bool(values) and all(isinstance(v, int | Decimal | Percent) for v in values)


def _widths(section: Section, width: float) -> list[float]:
    """Each column as wide as its longest text, within bounds, scaled to fill the page's text width."""
    lengths = [
        min(max([len(header), *(len(_text(row[column], header)) for row in section.rows)]), 24)
        for column, header in enumerate(section.headers)
    ]
    total = sum(max(length, 4) for length in lengths)
    return [width * max(length, 4) / total for length in lengths]


def _text(cell: Cell, header: str) -> str:
    match cell:
        case None:
            return ""
        case Percent(fraction):
            return format_percent(fraction * 100)
        case int():
            return str(cell)
        case Decimal():
            return format_quantity(cell) if header == _QUANTITY_HEADER else format_number(cell)
        case date():
            return format_date(cell)
        case _:
            return cell
