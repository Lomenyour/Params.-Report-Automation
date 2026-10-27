"""Rich text Excel для обозначений параметров с подстрочными индексами."""
import re

from openpyxl.chart.text import RichText
from openpyxl.drawing.text import (
    CharacterProperties, Font as DrawingFont, Paragraph, ParagraphProperties,
    RegularTextRun, RichTextProperties,
)


FONT_SIZE = 1400  # DrawingML: сотые доли пункта, то есть 14 пт.
_PARAMETERS = re.compile(
    r"ΔP(?:ВЛО|ФГО\+ФТО|ФГО|ФТО)|αВНА|NГТУ|Nгту|Nприв|bприв|ηГТУ|Nакт|tнк|Pнк|ηoi|πк"
)


def rich_text(text, *, size=FONT_SIZE, bold=False, centered=False):
    def properties(subscript=False):
        return CharacterProperties(
            sz=round(size * 0.75) if subscript else size,
            b=bold, solidFill="000000", baseline=-25000 if subscript else 0,
            latin=DrawingFont(typeface="Times New Roman"),
        )

    paragraphs = []
    for line in text.split("\n"):
        runs = []
        position = 0
        for match in _PARAMETERS.finditer(line):
            base_length = 2 if match[0].startswith("ΔP") else 1
            runs.append(RegularTextRun(
                rPr=properties(), t=line[position:match.start()] + match[0][:base_length],
            ))
            runs.append(RegularTextRun(rPr=properties(True), t=match[0][base_length:]))
            position = match.end()
        if position < len(line) or not runs:
            runs.append(RegularTextRun(rPr=properties(), t=line[position:]))
        paragraphs.append(Paragraph(
            pPr=ParagraphProperties(algn="ctr" if centered else None, defRPr=properties()),
            r=runs, endParaRPr=properties(),
        ))
    return RichText(bodyPr=RichTextProperties(wrap="none", spcFirstLastPara=False), p=paragraphs)
