"""Rich text Excel для обозначений параметров с подстрочными индексами."""
import re

from openpyxl.chart.text import RichText, Text
from openpyxl.chart.label import DataLabel, DataLabelList
from openpyxl.chart.series import SeriesLabel, XYSeries
from openpyxl.chart.data_source import AxDataSource, NumData, NumDataSource, NumVal
from openpyxl.chart.shapes import GraphicalProperties
from openpyxl.drawing.line import LineProperties
from openpyxl.utils.datetime import to_excel
from openpyxl.drawing.text import (
    CharacterProperties, Font as DrawingFont, Paragraph, ParagraphProperties,
    RegularTextRun, RichTextProperties,
)


FONT_SIZE = 1600  # DrawingML: сотые доли пункта, то есть 16 пт.
LABEL_SIZE = 1000
_PARAMETERS = re.compile(
    r"ΔP(?:ВЛО|ФГО\+ФТО|ФГО|ФТО)|αВНА|NГТУ|Nгту|Nприв|bприв|ηГТУ|Nакт|tнк|Pнк|ηoi|πк|Bчист|Bзагр"
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


class RichDataLabel(DataLabel):
    """Нативный c:tx с рамкой по тексту, без фиксированной ширины/высоты."""
    def __init__(self, text, *, bold=False, vertical=False, size=LABEL_SIZE):
        super().__init__(idx=0)
        self.text, self.bold, self.vertical = text, bold, vertical
        self.size = size

    def to_tree(self, tagname=None, idx=None, namespace=None):
        element = DataLabel(idx=self.idx, dLblPos="ctr", showSerName=False,
            showVal=False, showCatName=False, showLegendKey=False).to_tree(tagname, idx, namespace)
        text = rich_text(self.text, size=self.size, bold=self.bold, centered=True)
        text.bodyPr.spAutoFit = True
        text.bodyPr.lIns = text.bodyPr.rIns = 35000
        text.bodyPr.tIns = text.bodyPr.bIns = 25000
        if self.vertical:
            text.bodyPr.rot = -5400000
        element.insert(1, Text(rich=text).to_tree("tx"))
        return element


def label_series(x, y, text, *, dates=False, bold=False, color="000000", size=LABEL_SIZE):
    """Один блок подписи в координатах диаграммы, без служебных ячеек."""
    series = XYSeries(tx=SeriesLabel(v=text),
        xVal=AxDataSource(numLit=NumData(ptCount=1, pt=[NumVal(idx=0,
            v=to_excel(x.to_pydatetime()) if dates else float(x))])),
        yVal=NumDataSource(numLit=NumData(ptCount=1, pt=[NumVal(idx=0, v=float(y))])))
    series.marker.symbol = "none"
    series.graphicalProperties.line.noFill = True
    series.dLbls = DataLabelList(dLbl=[RichDataLabel(text, bold=bold, size=size)],
        showSerName=False, showVal=False, showCatName=False, showLegendKey=False,
        dLblPos="ctr", txPr=rich_text("", size=size, bold=bold, centered=True),
        spPr=GraphicalProperties(solidFill="FFFFFF", ln=LineProperties(solidFill=color, w=12700)))
    return series
