"""
Minimal Excel (.xlsx) writer - standard library only (zipfile + XML), so the .exe needs
no extra packages. Supports several sheets, bold coloured header row, column widths,
frozen header, auto-filter, numbers / text and per-cell fill colours.
"""
from __future__ import annotations

import datetime as _dt
import zipfile
from typing import Any, Dict, List, Optional, Sequence, Tuple
from xml.sax.saxutils import escape

# fills usable in cells: name -> ARGB
FILLS = {"green": "FFC8E6C9", "red": "FFFFCDD2", "amber": "FFFFE0B2", "grey": "FFECEFF1",
         "blue": "FFBBDEFB"}
_FILL_IDS = {name: 3 + i for i, name in enumerate(FILLS)}   # 0/1 reserved, 2 = header


def _col(n: int) -> str:
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _clean(text: str) -> str:
    # remove characters that are illegal in XML 1.0
    return "".join(ch for ch in text if ch in "\t\n\r" or ord(ch) >= 32)


class Sheet:
    def __init__(self, name: str, headers: Sequence[str], widths: Optional[Sequence[int]] = None):
        bad = '[]:*?/\\'
        self.name = "".join("_" if c in bad else c for c in name)[:31] or "Sheet"
        self.headers = list(headers)
        self.widths = list(widths) if widths else [max(10, min(45, len(h) + 4)) for h in headers]
        self.rows: List[Tuple[List[Any], Dict[int, str]]] = []
        self.header_row = True

    def add(self, values: Sequence[Any], fills: Optional[Dict[int, str]] = None):
        """fills: {column index: fill name from FILLS}"""
        self.rows.append((list(values), dict(fills or {})))


def _style_id(fill: Optional[str], bold: bool = False) -> int:
    if bold:
        return 1
    if fill and fill in _FILL_IDS:
        return 1 + _FILL_IDS[fill] - 2     # styles: 0 normal, 1 header, 2.. fills
    return 0


def _sheet_xml(sh: Sheet) -> str:
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
           '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
           'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">']
    if sh.header_row and sh.headers:
        out.append('<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
                   'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>')
    out.append("<cols>" + "".join(f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>'
                                  for i, w in enumerate(sh.widths)) + "</cols>")
    out.append("<sheetData>")
    r = 1
    if sh.headers:
        cells = "".join(f'<c r="{_col(i)}{r}" t="inlineStr" s="1"><is><t>{escape(_clean(str(h)))}'
                        f'</t></is></c>' for i, h in enumerate(sh.headers))
        out.append(f'<row r="{r}">{cells}</row>')
        r += 1
    for values, fills in sh.rows:
        cells = []
        for i, v in enumerate(values):
            ref = f"{_col(i)}{r}"
            s = _style_id(fills.get(i))
            sattr = f' s="{s}"' if s else ""
            if v is None or v == "":
                if s:
                    cells.append(f'<c r="{ref}"{sattr}/>')
                continue
            if isinstance(v, bool):
                cells.append(f'<c r="{ref}" t="inlineStr"{sattr}><is><t>{"TRUE" if v else "FALSE"}'
                             f'</t></is></c>')
            elif isinstance(v, (int, float)):
                cells.append(f'<c r="{ref}"{sattr}><v>{v}</v></c>')
            else:
                txt = escape(_clean(str(v)))
                cells.append(f'<c r="{ref}" t="inlineStr"{sattr}><is><t xml:space="preserve">{txt}'
                             f'</t></is></c>')
        out.append(f'<row r="{r}">{"".join(cells)}</row>')
        r += 1
    out.append("</sheetData>")
    if sh.headers and sh.rows:
        out.append(f'<autoFilter ref="A1:{_col(len(sh.headers) - 1)}{r - 1}"/>')
    out.append("</worksheet>")
    return "".join(out)


def _styles_xml() -> str:
    fills = ['<fill><patternFill patternType="none"/></fill>',
             '<fill><patternFill patternType="gray125"/></fill>',
             '<fill><patternFill patternType="solid"><fgColor rgb="FF2E7D32"/><bgColor indexed="64"/>'
             '</patternFill></fill>']
    fills += [f'<fill><patternFill patternType="solid"><fgColor rgb="{argb}"/><bgColor indexed="64"/>'
              f'</patternFill></fill>' for argb in FILLS.values()]
    xfs = ['<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>',
           '<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" '
           'applyFill="1" applyBorder="1"/>']
    xfs += [f'<xf numFmtId="0" fontId="0" fillId="{fid}" borderId="0" xfId="0" applyFill="1"/>'
            for fid in _FILL_IDS.values()]
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
            '<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font></fonts>'
            f'<fills count="{len(fills)}">{"".join(fills)}</fills>'
            '<borders count="2"><border/><border><bottom style="thin"><color rgb="FF1B5E20"/>'
            '</bottom></border></borders>'
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            f'<cellXfs count="{len(xfs)}">{"".join(xfs)}</cellXfs>'
            '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
            '</styleSheet>')


def write_xlsx(path: str, sheets: Sequence[Sheet], title: str = "", author: str = ""):
    names = [s.name for s in sheets]
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
          '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
          '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
          + "".join(f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" '
                    f'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                    for i in range(len(sheets))) + '</Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
            '</Relationships>')
    wb = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
          + "".join(f'<sheet name="{escape(n)}" sheetId="{i + 1}" r:id="rId{i + 1}"/>'
                    for i, n in enumerate(names)) + '</sheets>'
          + ('<definedNames>' + "".join(
              f'<definedName name="_xlnm._FilterDatabase" localSheetId="{i}" hidden="1">'
              f"'{escape(s.name)}'!$A$1:${_col(len(s.headers) - 1)}${len(s.rows) + 1}</definedName>"
              for i, s in enumerate(sheets) if s.headers and s.rows) + '</definedNames>'
             if any(s.headers and s.rows for s in sheets) else '')
          + '</workbook>')
    wbrels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
              + "".join(f'<Relationship Id="rId{i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i + 1}.xml"/>'
                        for i in range(len(sheets)))
              + f'<Relationship Id="rId{len(sheets) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
              '</Relationships>')
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f'<dc:title>{escape(title)}</dc:title><dc:creator>{escape(author)}</dc:creator>'
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>'
            '</cp:coreProperties>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        z.writestr("docProps/core.xml", core)
        z.writestr("xl/workbook.xml", wb)
        z.writestr("xl/_rels/workbook.xml.rels", wbrels)
        z.writestr("xl/styles.xml", _styles_xml())
        for i, sh in enumerate(sheets):
            z.writestr(f"xl/worksheets/sheet{i + 1}.xml", _sheet_xml(sh))
