"""文献/研报结构化解析与清洗模块 (Document Parser).

功能:
  1. 支持金融金工研报 (Research Report)、学术论文 PDF (Academic Paper)、Markdown 与社区讨论贴 (Forum Post)
  2. 内置零依赖纯 Python PDF 流解析引擎与文件读取器
  3. 自动提取标题、核心摘要、数学公式代码块与关键方法论
  4. 过滤免责声明、机构合规声明、页眉页脚等非结构化噪声
"""

from __future__ import annotations

import os
import re
import zlib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union


class DocumentType(str, Enum):
    """文献类型枚举."""

    RESEARCH_REPORT = "research_report"  # 券商金工研报
    ACADEMIC_PAPER = "academic_paper"    # 学术论文 (SSRN / arXiv)
    FORUM_POST = "forum_post"            # 量化社区帖子 / 研报速递
    RAW_TEXT = "raw_text"                # 纯文本 / 代码片段


@dataclass
class ParsedDocument:
    """结构化解析后的文献对象."""

    title: str
    doc_type: DocumentType
    abstract: str
    clean_text: str
    formulas_found: List[str] = field(default_factory=list)
    raw_content: str = ""


# 常见金融研报噪声模式 (免责声明、评级说明等)
_DISCLAIMER_PATTERNS = [
    r"免责声明[\s\S]*?(?=\n#|\Z)",
    r"风险提示[\s\S]*?(?=\n#|\Z)",
    r"评级说明[\s\S]*?(?=\n#|\Z)",
    r"本报告由.*?证券研究所制作[\s\S]*?(?=\n|\Z)",
    r"All rights reserved[\s\S]*?(?=\n|\Z)",
]


def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    """零依赖纯 Python 提取 PDF 字节流中的文本内容."""
    text_pieces: List[str] = []

    # 1. 扫描所有 stream ... endstream 数据块
    stream_matches = re.finditer(b"stream[\r\n]+(.*?)[\r\n]+endstream", pdf_bytes, re.DOTALL)
    for m in stream_matches:
        raw_stream = m.group(1)
        try:
            decomp = zlib.decompress(raw_stream)
        except Exception:
            decomp = raw_stream

        # 提取括号内的文本对象 \( (.*?) \)
        strs = re.findall(b"\\((.*?)\\)", decomp)
        for s in strs:
            try:
                decoded = s.decode("latin1", errors="ignore")
                decoded_clean = decoded.strip()
                if len(decoded_clean) >= 1 and not decoded_clean.startswith("\xff\xfe"):
                    text_pieces.append(decoded_clean)
            except Exception:
                pass

    if text_pieces:
        # 重组单词与换行
        joined = " ".join(text_pieces)
        # 清理转义字符
        joined = re.sub(r"\\\d{3}", "", joined)
        return joined

    return ""


def load_literature_content(source: Union[str, Path]) -> Tuple[str, DocumentType, Optional[str]]:
    """智能读取文献源 (支持 PDF 路径、文本路径或原始字符串).

    Returns:
        (content_text, document_type, title_hint)
    """
    if isinstance(source, Path) or (isinstance(source, str) and os.path.exists(source)):
        file_path = Path(source)
        title_hint = file_path.stem.replace("_", " ")

        if file_path.suffix.lower() == ".pdf":
            # 读取 PDF
            pdf_bytes = file_path.read_bytes()
            extracted_text = extract_text_from_pdf_bytes(pdf_bytes)
            if not extracted_text:
                extracted_text = f"# {title_hint}\n(Extracted from PDF: {file_path.name})"
            return extracted_text, DocumentType.ACADEMIC_PAPER, title_hint
        else:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
            doc_type = DocumentType.RESEARCH_REPORT if "研报" in text or "证券" in text else DocumentType.ACADEMIC_PAPER
            return text, doc_type, title_hint

    # 纯文本输入
    raw_str = str(source)
    doc_type = DocumentType.RAW_TEXT
    if "abstract" in raw_str.lower() or "arxiv" in raw_str.lower() or "ssrn" in raw_str.lower():
        doc_type = DocumentType.ACADEMIC_PAPER
    elif "研报" in raw_str or "证券" in raw_str:
        doc_type = DocumentType.RESEARCH_REPORT

    return raw_str, doc_type, None


def clean_literature_text(raw_text: str) -> str:
    """清洗文献文本，去除噪声声明与冗余空白."""
    cleaned = raw_text
    for pat in _DISCLAIMER_PATTERNS:
        cleaned = re.sub(pat, "", cleaned, flags=re.IGNORECASE)

    # 去除连续空行
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def extract_formulas_from_text(text: str) -> List[str]:
    """从文本中提取代码块公式、LaTeX 公式与常见数学表达式 (包括纯基本面/分析师/量价等任意自定义公式)."""
    formulas: List[str] = []

    # 1. Markdown 代码块 ```python / ```
    code_blocks = re.findall(r"```(?:python|fastexpr|latex)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    for cb in code_blocks:
        lines = [line.strip() for line in cb.splitlines() if line.strip() and not line.strip().startswith("#")]
        formulas.extend(lines)

    # 2. LaTeX 独立公式 $$ ... $$
    latex_blocks = re.findall(r"\$\$([\s\S]*?)\$\$", text)
    formulas.extend([lb.strip() for lb in latex_blocks if lb.strip()])

    # 3. 赋值语句行 (如 Alpha_1 = rank(...) / ... 或 Signal = ...)
    assignment_lines = re.findall(r"(?:^|\n)\s*[a-zA-Z_]\w*\s*[:=]\s*([a-zA-Z_]\w*\(.+\))\s*(?:\n|$)", text)
    formulas.extend([al.strip() for al in assignment_lines if len(al.strip()) > 5])

    # 4. 常见量化表达式行 (如含有 rank, ts_rank, / , - 且包含括号)
    quant_lines = re.findall(r"(?:^|\n)\s*([a-zA-Z_]\w*\s*\([^;\n]+\))\s*(?:\n|$)", text)
    formulas.extend([ql.strip() for ql in quant_lines if len(ql.strip()) > 5])

    # 去重并去除外层赋值符号
    seen = set()
    unique_formulas = []
    for f in formulas:
        f_clean = f.strip().rstrip(";")
        # 如果包含类似 "Alpha = " 前缀，剥离左侧变量赋值
        if "=" in f_clean and not any(eq in f_clean for eq in ("==", "<=", ">=")):
            parts = f_clean.split("=", 1)
            if re.match(r"^\s*[a-zA-Z_]\w*\s*$", parts[0]):
                f_clean = parts[1].strip()

        if f_clean and f_clean not in seen and len(f_clean) > 3:
            seen.add(f_clean)
            unique_formulas.append(f_clean)

    return unique_formulas


def parse_document(
    content: Union[str, Path],
    doc_type: Optional[DocumentType] = None,
    title_hint: Optional[str] = None,
) -> ParsedDocument:
    """对文献/研报源（支持 PDF 文件路径、文本文件或字符串）执行结构化解析."""
    raw_text, auto_doc_type, auto_title = load_literature_content(content)
    final_doc_type = doc_type or auto_doc_type
    final_title_hint = title_hint or auto_title

    cleaned = clean_literature_text(raw_text)

    # 1. 提取标题 (优先以 # 一级标题为准)
    title = final_title_hint or ""
    if not title:
        title_match = re.search(r"^#\s+(.+)$", cleaned, re.MULTILINE)
        if title_match:
            title = title_match.group(1).strip()
        else:
            first_line = cleaned.splitlines()[0].strip() if cleaned.splitlines() else "Untitled Research Idea"
            title = first_line[:60]

    # 2. 提取摘要 (Abstract)
    abstract = ""
    abstract_match = re.search(r"(?:摘要|核心观点|Abstract)[:：\s]+([\s\S]*?)(?=\n#|\n\n[1-9]|\Z)", cleaned, re.IGNORECASE)
    if abstract_match:
        abstract = abstract_match.group(1).strip()[:400]
    else:
        abstract = cleaned[:300]

    # 3. 提取公式
    formulas = extract_formulas_from_text(cleaned)

    return ParsedDocument(
        title=title,
        doc_type=final_doc_type,
        abstract=abstract,
        clean_text=cleaned,
        formulas_found=formulas,
        raw_content=raw_text,
    )
