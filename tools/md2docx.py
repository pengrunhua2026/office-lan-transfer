# -*- coding: utf-8 -*-
"""
Markdown → Word (.docx) 转换脚本
================================
把本项目的 design.md / README.md 等 Markdown 文档转换为符合 Word 排版规范的
docx 文档（标题黑体、正文宋体、表格规范、动态目录等）。

【设计思路】
  1. 为什么自写转换脚本，而非用现成工具？
     项目文档有固定的中文排版规范（标题黑体、正文宋体、首行缩进 2 字符、
     表格浅灰表头、行不跨页等），自写脚本可完全掌控这些排版细节，
     且便于在 CI / 手动重生成时反复复现同样的产物。
  2. 排版规范集中实现：
     字体常量（SONG/HEI/KAI）与 set_run_font / add_para / add_heading / add_table
     等函数统一实现所有排版规则，任何文档都走同一套样式，保证风格一致。
  3. Markdown 解析为轻量状态机：
     逐行扫描（while i < n），识别代码块、标题、分隔线、表格、无序/有序列表、
     引用、空行、普通段落，避免引入第三方解析器依赖，逻辑直观可控。
  4. 封面版本自动提取：
     封面版本从 Markdown 全文正则提取"版本：vX.Y.Z"，避免封面与正文版本写死不一致。

用法（在项目根目录下）：
  python tools/md2docx.py <输入.md> <输出.docx> [--cover] [--toc]

  --cover : 生成封面（软件名、文档名、版本、开发者、日期）
  --toc   : 插入动态目录（TOC 域），正文从新页开始
"""
import sys
import re
from datetime import datetime

from docx import Document
from docx.shared import Pt, RGBColor, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

# ---------------- 常量 ----------------
SONG = "宋体"
HEI = "黑体"
KAI = "楷体"
WEST = "Times New Roman"
MONO = "Consolas"

BLACK = RGBColor(0x00, 0x00, 0x00)


def set_run_font(run, cn_font, size, bold=False, west=WEST, color=BLACK):
    """设置 run 的中西文字体、字号、加粗与颜色。"""
    run.font.name = west
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:ascii"), west)
    rfonts.set(qn("w:hAnsi"), west)
    rfonts.set(qn("w:eastAsia"), cn_font)


def add_para(doc, text, cn_font=SONG, size=12, bold=False, align=WD_ALIGN_PARAGRAPH.JUSTIFY,
             first_indent=True, spacing=1.5, before=0, after=0, west=WEST):
    """按规范添加一个正文段落。

    【设计思路】
    - 默认两端对齐、1.5 倍行距；first_indent=True 时用 firstLineChars=200
      实现"首行缩进 2 字符"（用字符数而非磅值，保证不同字号下缩进一致）。
    - 文本支持内联富文本：**加粗** 与 `代码`，由 parse_inline 拆分后逐段设置字体。
    """
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.alignment = align
    pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
    pf.line_spacing = spacing
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    if first_indent:
        # 首行缩进 2 字符
        ind = OxmlElement("w:ind")
        ind.set(qn("w:firstLineChars"), "200")
        p._p.get_or_add_pPr().append(ind)
    # 富文本解析：**加粗** 与 `代码`
    for seg, is_code, is_bold in parse_inline(text):
        run = p.add_run(seg)
        if is_code:
            set_run_font(run, MONO, size, bold=False, west=MONO)
        else:
            set_run_font(run, cn_font, size, bold=bold or is_bold, west=west)
    return p


def parse_inline(text):
    """解析内联格式，返回 [(文本, 是否代码, 是否加粗), ...]。"""
    segs = []
    # 先按代码段 `...` 切分
    parts = re.split(r"(`[^`]+`)", text)
    for part in parts:
        if part.startswith("`") and part.endswith("`"):
            segs.append((part[1:-1], True, False))
        else:
            # 再按 **加粗** 切分
            sub = re.split(r"(\*\*[^*]+\*\*)", part)
            for s in sub:
                if s.startswith("**") and s.endswith("**"):
                    segs.append((s[2:-2], False, True))
                elif s:
                    segs.append((s, False, False))
    return segs


def add_heading(doc, text, level):
    """按规范添加标题（Heading 样式 + 黑体）。"""
    sizes = {0: 18, 1: 16, 2: 14, 3: 12}
    before = {0: 0, 1: 14, 2: 11, 3: 9}
    after = {0: 18, 1: 6, 2: 5, 3: 4}
    h = doc.add_paragraph()
    h.style = doc.styles["Heading %d" % level] if level > 0 else doc.styles["Title"]
    pf = h.paragraph_format
    pf.alignment = WD_ALIGN_PARAGRAPH.LEFT if level > 0 else WD_ALIGN_PARAGRAPH.CENTER
    pf.space_before = Pt(before[level])
    pf.space_after = Pt(after[level])
    pf.line_spacing_rule = WD_LINE_SPACING.SINGLE
    run = h.add_run(text)
    set_run_font(run, HEI, sizes[level], bold=True)
    return h


def set_cell_text(cell, text, bold=False, align=WD_ALIGN_PARAGRAPH.LEFT):
    """设置单元格文本与对齐。"""
    cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    cell.text = ""
    p = cell.paragraphs[0]
    p.paragraph_format.alignment = align
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
    for seg, is_code, is_bold in parse_inline(text):
        run = p.add_run(seg)
        font = MONO if is_code else SONG
        set_run_font(run, font, 10.5, bold=bold or is_bold)


def set_row_cant_split(row):
    """设置表格行不跨页拆分。"""
    trPr = row._tr.get_or_add_trPr()
    cant = OxmlElement("w:cantSplit")
    trPr.append(cant)


def set_row_header(row):
    """设置表头行跨页重复显示。"""
    trPr = row._tr.get_or_add_trPr()
    tblHeader = OxmlElement("w:tblHeader")
    tblHeader.set(qn("w:val"), "true")
    trPr.append(tblHeader)


def add_table(doc, rows):
    """按规范添加表格。rows 为二维列表，首行为表头。

    【设计思路】
    - 使用"Table Grid"网格样式 + 居中；表头行浅灰底（D9D9D9）、加粗、居中。
    - 表头行设置跨页重复（set_row_header），数据行设置不跨页拆分（set_row_cant_split），
      保证长表格跨页时表头始终可见、行不被拦腰截断。
    """
    if not rows:
        return
    table = doc.add_table(rows=len(rows), cols=len(rows[0]))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    # 表头背景浅灰
    for j, cell in enumerate(table.rows[0].cells):
        shd = OxmlElement("w:shd")
        shd.set(qn("w:fill"), "D9D9D9")
        shd.set(qn("w:val"), "clear")
        cell._tc.get_or_add_tcPr().append(shd)
        set_cell_text(cell, rows[0][j], bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
    set_row_header(table.rows[0])
    for i in range(1, len(rows)):
        for j, cell in enumerate(table.rows[i].cells):
            set_cell_text(cell, rows[i][j])
        set_row_cant_split(table.rows[i])
    # 表后留一个空段
    sp = doc.add_paragraph()
    sp.paragraph_format.space_after = Pt(6)
    return table


def add_code_block(doc, code):
    """添加代码块（等宽字体、浅底、单倍行距）。"""
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_before = Pt(4)
    pf.space_after = Pt(8)
    pf.line_spacing_rule = WD_LINE_SPACING.SINGLE
    pf.left_indent = Cm(0.5)
    run = p.add_run(code.strip("\n"))
    set_run_font(run, MONO, 9, west=MONO)
    # 浅灰底纹
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), "F2F2F2")
    shd.set(qn("w:val"), "clear")
    p._p.get_or_add_pPr().append(shd)
    return p


def add_toc(doc):
    """插入动态目录（TOC 域，两级）。

    【设计思路】
    - 插入一个真正的"目录域"（fldChar begin/instrText/separate/end），
      Word 中按 F9 或打开时会自动按 Heading 1-2 生成带页码的目录。
    - 显式设置占位文本的宋体字体，避免被默认主题映射为日文字体（ＴＭＳ明朝）。
    """
    p = doc.add_paragraph()
    run = p.add_run()
    fld_char = OxmlElement("w:fldChar")
    fld_char.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = ' TOC \\o "1-2" \\h \\z \\u '
    fld_sep = OxmlElement("w:fldChar")
    fld_sep.set(qn("w:fldCharType"), "separate")
    t_el = OxmlElement("w:t")
    t_el.text = "（目录请在 Word 中按 F9 刷新）"
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    run._r.append(fld_char)
    run._r.append(instr)
    run._r.append(fld_sep)
    run._r.append(t_el)
    run._r.append(fld_end)
    # 显式设置占位文本字体，避免被默认主题映射为日文字体
    set_run_font(run, SONG, 12)
    return p


def add_page_break(doc):
    doc.add_page_break()


def add_cover(doc, doc_title, subtitle="", version="v2.0.0.0"):
    """添加封面。"""
    # 空行占位
    for _ in range(4):
        add_para(doc, "", cn_font=SONG, size=12, first_indent=False, spacing=1.5)
    add_para(doc, "局域网办公文件传输系统", cn_font=HEI, size=18, bold=True,
             align=WD_ALIGN_PARAGRAPH.CENTER, first_indent=False, after=6)
    add_para(doc, doc_title, cn_font=KAI, size=12,
             align=WD_ALIGN_PARAGRAPH.CENTER, first_indent=False, after=18)
    for _ in range(6):
        add_para(doc, "", cn_font=SONG, size=12, first_indent=False, spacing=1.5)
    add_para(doc, "版本：%s" % version, align=WD_ALIGN_PARAGRAPH.CENTER, first_indent=False)
    add_para(doc, "开发者：prh", align=WD_ALIGN_PARAGRAPH.CENTER, first_indent=False)
    add_para(doc, "日期：%s" % datetime.now().strftime("%Y-%m-%d"),
             align=WD_ALIGN_PARAGRAPH.CENTER, first_indent=False)
    add_page_break(doc)


def md_to_docx(md_path, out_path, cover=False, toc=False):
    """把 Markdown 文件转换为 docx。

    【设计思路】
    - 文档初始化：设置默认中文字体（避免主题映射为日文字体）、A4 页面 + 2.5cm 页边距。
    - 封面：从 Markdown 全文正则提取"版本：vX.Y.Z"传给 add_cover，
      确保封面版本与正文一致（不写死）。
    - 正文用"轻量状态机"逐行解析：代码块/标题/分隔线/表格/列表/引用/空行/段落。
    """
    with open(md_path, encoding="utf-8") as f:
        lines = f.read().splitlines()

    doc = Document()
    # 设置默认样式的中文字体，避免主题将中文映射为日文字体（ＴＭＳ明朝）
    _st = doc.styles["Normal"]
    _st.font.name = WEST
    _st.font.size = Pt(12)
    _rpr = _st.element.get_or_add_rPr()
    _rf = _rpr.find(qn("w:rFonts"))
    if _rf is None:
        _rf = OxmlElement("w:rFonts")
        _rpr.append(_rf)
    _rf.set(qn("w:ascii"), WEST)
    _rf.set(qn("w:hAnsi"), WEST)
    _rf.set(qn("w:eastAsia"), SONG)
    # 页面设置 A4 + 2.5cm 页边距
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    sec.top_margin = sec.bottom_margin = Cm(2.5)
    sec.left_margin = sec.right_margin = Cm(2.5)

    if cover:
        doctype = "使用说明" if "使用说明" in out_path else "详细设计说明书"
        # 从 Markdown 全文提取版本号（如 "- 版本：v2.1.0.0"），避免封面版本写死
        version = "v2.0.0.0"
        m = re.search(r"版本：\s*v?([\d.]+)", "\n".join(lines))
        if m:
            version = "v" + m.group(1)
        add_cover(doc, doctype, version=version)
    if toc:
        add_para(doc, "目  录", cn_font=HEI, size=16, bold=True,
                 align=WD_ALIGN_PARAGRAPH.CENTER, first_indent=False, before=6, after=12)
        add_toc(doc)
        add_page_break(doc)

    # 状态机：代码块
    in_code = False
    code_lines = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i].rstrip()

        # 代码块
        if line.strip().startswith("```"):
            if not in_code:
                in_code = True
                code_lines = []
            else:
                add_code_block(doc, "\n".join(code_lines))
                in_code = False
            i += 1
            continue
        if in_code:
            code_lines.append(line)
            i += 1
            continue

        # 标题
        m = re.match(r"^(#{1,4})\s+(.*)$", line)
        if m:
            level = len(m.group(1))
            text = m.group(2).strip()
            if level == 1 and line.startswith("# "):
                add_heading(doc, text, 0)  # Title
            else:
                add_heading(doc, text, min(level, 3))
            i += 1
            continue

        # 分隔线
        if re.match(r"^\s*---+\s*$", line):
            add_para(doc, "", first_indent=False)
            i += 1
            continue

        # 表格：以 | 开头且下一行是分隔行
        if line.lstrip().startswith("|") and i + 1 < n:
            j = i + 1
            if re.match(r"^\s*\|[\s:\-|]+\|\s*$", lines[j]) or \
               re.match(r"^\s*\|[\s:\-|]+\s*$", lines[j]):
                rows = []
                header = [c.strip() for c in line.strip().strip("|").split("|")]
                rows.append(header)
                k = j + 1
                while k < n and lines[k].lstrip().startswith("|"):
                    row = [c.strip() for c in lines[k].strip().strip("|").split("|")]
                    rows.append(row)
                    k += 1
                add_table(doc, rows)
                i = k
                continue

        # 无序列表
        if re.match(r"^\s*[-*]\s+", line):
            text = re.sub(r"^\s*[-*]\s+", "", line)
            p = add_para(doc, "• " + text, first_indent=False, spacing=1.0, after=2)
            p.paragraph_format.left_indent = Cm(0.6)
            i += 1
            continue

        # 有序列表
        m = re.match(r"^\s*\d+\.\s+(.*)$", line)
        if m:
            p = add_para(doc, m.group(1), first_indent=False, spacing=1.0, after=2)
            p.paragraph_format.left_indent = Cm(0.6)
            i += 1
            continue

        # 引用
        if line.lstrip().startswith(">"):
            text = line.lstrip()[1:].strip()
            add_para(doc, text, first_indent=False, after=4)
            i += 1
            continue

        # 空行
        if not line.strip():
            i += 1
            continue

        # 普通段落
        add_para(doc, line, first_indent=True, after=4)
        i += 1

    doc.save(out_path)
    print("saved:", out_path)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = set(a for a in sys.argv[1:] if a.startswith("--"))
    if len(args) < 2:
        print(__doc__)
        sys.exit(1)
    md_to_docx(args[0], args[1], cover="--cover" in flags, toc="--toc" in flags)
