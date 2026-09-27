"""A minimal Excel (.xlsx) writer: Office Open XML with the standard library only.

Enough for data exports: several sheets, bold header row, frozen first row, column widths and
number formats (thousands with one decimal, percent, two decimals).
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field
from xml.sax.saxutils import escape

STYLES = {"text": 0, "bold": 1, "num1": 2, "pct": 3, "num2": 4, "int": 5}
_BAD_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


@dataclass
class Sheet:
    name: str
    rows: list[list] = field(default_factory=list)   # cell = value or (value, style)
    widths: list[float] = field(default_factory=list)
    freeze_header: bool = True


def _col(index: int) -> str:
    name = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        name = chr(65 + rem) + name
    return name


def _sheet_name(name: str, used: set[str]) -> str:
    clean = re.sub(r"[\[\]:*?/\\]", " ", name).strip()[:31] or "Tabelle"
    base, n = clean, 2
    while clean.lower() in used:
        suffix = f" ({n})"
        clean = base[: 31 - len(suffix)] + suffix
        n += 1
    used.add(clean.lower())
    return clean


def _cell(ref: str, value, style: str | None) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        value = int(value)
    if isinstance(value, (int, float)):
        s = f' s="{STYLES[style or ("int" if isinstance(value, int) else "num1")]}"'
        return f'<c r="{ref}"{s}><v>{value!r}</v></c>'
    text = escape(_BAD_CHARS.sub("", str(value)))
    s = f' s="{STYLES[style]}"' if style else ""
    return f'<c r="{ref}" t="inlineStr"{s}><is><t xml:space="preserve">{text}</t></is></c>'


def _worksheet(sheet: Sheet) -> str:
    rows_xml = []
    for r, row in enumerate(sheet.rows, 1):
        cells = []
        for c, item in enumerate(row):
            value, style = item if isinstance(item, tuple) else (item, None)
            if r == 1 and style is None and sheet.freeze_header:
                style = "bold"
            cells.append(_cell(f"{_col(c)}{r}", value, style))
        rows_xml.append(f'<row r="{r}">{"".join(cells)}</row>')
    cols = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>' for i, w in enumerate(sheet.widths))
    pane = ('<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" '
            'state="frozen"/></sheetView></sheetViews>') if sheet.freeze_header and sheet.rows else ""
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'{pane}{f"<cols>{cols}</cols>" if cols else ""}<sheetData>{"".join(rows_xml)}</sheetData></worksheet>')


STYLES_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<numFmts count="2"><numFmt numFmtId="164" formatCode="#,##0.0"/><numFmt numFmtId="165" formatCode="0.0%"/></numFmts>'
    '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
    '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="6">'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
    '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
    '<xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
    '<xf numFmtId="2" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
    '<xf numFmtId="1" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
    '</cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')


def workbook(sheets: list[Sheet]) -> bytes:
    used: set[str] = set()
    names = [_sheet_name(s.name, used) for s in sheets]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        overrides = "".join(
            f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for i in range(1, len(sheets) + 1))
        zf.writestr("[Content_Types].xml",
                    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                    '<Default Extension="xml" ContentType="application/xml"/>'
                    '<Override PartName="/xl/workbook.xml" '
                    'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                    '<Override PartName="/xl/styles.xml" '
                    'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                    f'{overrides}</Types>')
        zf.writestr("_rels/.rels",
                    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
                    'officeDocument" Target="xl/workbook.xml"/></Relationships>')
        sheet_tags = "".join(f'<sheet name="{escape(n)}" sheetId="{i}" r:id="rId{i}"/>' for i, n in enumerate(names, 1))
        zf.writestr("xl/workbook.xml",
                    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                    f'<sheets>{sheet_tags}</sheets></workbook>')
        rels = "".join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                       f'relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(sheets) + 1))
        zf.writestr("xl/_rels/workbook.xml.rels",
                    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    f'{rels}<Relationship Id="rId{len(sheets) + 1}" Type="http://schemas.openxmlformats.org/'
                    'officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        zf.writestr("xl/styles.xml", STYLES_XML)
        for i, sheet in enumerate(sheets, 1):
            zf.writestr(f"xl/worksheets/sheet{i}.xml", _worksheet(sheet))
    return buf.getvalue()
