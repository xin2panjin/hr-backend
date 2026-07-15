"""知识库统一文本提取器测试。"""

import zipfile
from pathlib import Path

import pymupdf
import pytest

from services.knowledge_text_extractor import (
    KnowledgeTextExtractionError,
    KnowledgeTextExtractor,
)


def write_minimal_docx(path: Path) -> None:
    """写入包含两级标题与正文的最小 DOCX OpenXML 文件。"""

    document_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body>
        <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>员工休假制度</w:t></w:r></w:p>
        <w:p><w:r><w:t>本制度适用于全体员工。</w:t></w:r></w:p>
        <w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>年假规则</w:t></w:r></w:p>
        <w:p><w:r><w:t>员工每年享有年假。</w:t></w:r></w:p>
      </w:body>
    </w:document>"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document_xml)


def write_test_pdf(path: Path) -> None:
    """生成两页带文本的 PDF，验证页码保留。"""

    with pymupdf.open() as document:
        first_page = document.new_page()
        first_page.insert_text((72, 72), "First page policy")
        second_page = document.new_page()
        second_page.insert_text((72, 72), "Second page annual leave")
        document.save(path)


def test_extract_markdown_preserves_heading_path_and_paragraph_boundaries(tmp_path):
    source_path = tmp_path / "policy.md"
    source_path.write_text(
        "# 员工手册\n\n适用于全体员工。\n\n## 年假规则\n\n员工每年享有年假。\n\n"
        "- 入职满一年后可申请\n- 具体天数以制度为准\n",
        encoding="utf-8",
    )

    blocks = KnowledgeTextExtractor().extract(file_path=source_path)

    assert [(block.text, block.section_path, block.page_number) for block in blocks] == [
        ("适用于全体员工。", "员工手册", None),
        ("员工每年享有年假。", "员工手册 > 年假规则", None),
        ("- 入职满一年后可申请\n- 具体天数以制度为准", "员工手册 > 年假规则", None),
    ]


def test_extract_txt_splits_paragraphs_without_interpreting_headings(tmp_path):
    source_path = tmp_path / "policy.txt"
    source_path.write_text("# 这不是标题\n第一段\n\n第二段", encoding="utf-8")

    blocks = KnowledgeTextExtractor().extract(file_path=source_path, file_type="txt")

    assert [block.text for block in blocks] == ["# 这不是标题\n第一段", "第二段"]
    assert all(block.section_path is None and block.page_number is None for block in blocks)


def test_extract_docx_recovers_heading_style_hierarchy(tmp_path):
    source_path = tmp_path / "policy.docx"
    write_minimal_docx(source_path)

    blocks = KnowledgeTextExtractor().extract(file_path=source_path)

    assert [(block.text, block.section_path, block.page_number) for block in blocks] == [
        ("本制度适用于全体员工。", "员工休假制度", None),
        ("员工每年享有年假。", "员工休假制度 > 年假规则", None),
    ]


def test_extract_pdf_preserves_page_numbers(tmp_path):
    source_path = tmp_path / "policy.pdf"
    write_test_pdf(source_path)

    blocks = KnowledgeTextExtractor().extract(file_path=source_path)

    assert any("First page policy" in block.text and block.page_number == 1 for block in blocks)
    assert any(
        "Second page annual leave" in block.text and block.page_number == 2
        for block in blocks
    )
    assert all(block.section_path is None for block in blocks)


def test_extract_rejects_empty_and_unsupported_documents(tmp_path):
    extractor = KnowledgeTextExtractor()
    empty_path = tmp_path / "empty.md"
    empty_path.write_text("\n\n", encoding="utf-8")
    unsupported_path = tmp_path / "policy.xlsx"
    unsupported_path.write_bytes(b"not-an-xlsx")

    with pytest.raises(KnowledgeTextExtractionError, match="未提取到有效文本"):
        extractor.extract(file_path=empty_path)
    with pytest.raises(KnowledgeTextExtractionError, match="不支持的文档类型"):
        extractor.extract(file_path=unsupported_path)
