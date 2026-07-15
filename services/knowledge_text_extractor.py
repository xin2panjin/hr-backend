"""知识库文档的统一文本提取器。

提取层只负责把不同文件格式转换为带来源定位信息的文本块，不执行清洗、
切片、Embedding 或 Milvus 写入。后续索引服务可据此统一处理四类文档。
"""

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from xml.etree import ElementTree

import pymupdf


class KnowledgeTextExtractionError(RuntimeError):
    """文档无法读取、格式不支持或未能提取有效文本。"""


@dataclass(frozen=True, slots=True)
class ExtractedTextBlock:
    """统一的文档文本块。

    ``page_number`` 对 PDF 从 1 开始；Markdown、TXT、DOCX 无可靠页码时为
    ``None``。``section_path`` 保存可恢复的标题层级，供后续结构化切片和
    来源引用使用。
    """

    text: str
    page_number: int | None = None
    section_path: str | None = None


class KnowledgeTextExtractor:
    """按文件类型提取 PDF、DOCX、Markdown 和 TXT 的文本块。"""

    SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".md", ".markdown", ".txt"}
    _MARKDOWN_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
    _WORD_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

    def extract(
        self,
        *,
        file_path: str | Path,
        file_type: str | None = None,
    ) -> list[ExtractedTextBlock]:
        """提取文件并返回非空文本块。

        ``file_type`` 可传数据库中的 ``pdf``、``docx`` 等值；未传时根据文件
        后缀判断。扫描型 PDF 不在本阶段 OCR，因而会以“未提取有效文本”失败，
        由后续流程标记为索引失败或进入 OCR 增强路径。
        """

        source_path = Path(file_path)
        if not source_path.is_file():
            raise KnowledgeTextExtractionError(f"文档文件不存在：{source_path}")

        extension = self._normalize_extension(file_type or source_path.suffix)
        extractor = self._get_extractor(extension)
        try:
            blocks = extractor(source_path)
        except KnowledgeTextExtractionError:
            raise
        except Exception as error:
            raise KnowledgeTextExtractionError(
                f"文档文本提取失败：{source_path.name}"
            ) from error

        non_empty_blocks = [block for block in blocks if block.text.strip()]
        if not non_empty_blocks:
            raise KnowledgeTextExtractionError(f"未提取到有效文本：{source_path.name}")
        return non_empty_blocks

    def _get_extractor(
        self,
        extension: str,
    ) -> Callable[[Path], list[ExtractedTextBlock]]:
        extractors = {
            ".pdf": self._extract_pdf,
            ".docx": self._extract_docx,
            ".md": self._extract_markdown,
            ".markdown": self._extract_markdown,
            ".txt": self._extract_txt,
        }
        try:
            return extractors[extension]
        except KeyError as error:
            supported_extensions = ", ".join(sorted(self.SUPPORTED_EXTENSIONS))
            raise KnowledgeTextExtractionError(
                f"不支持的文档类型：{extension or '无后缀'}；"
                f"支持：{supported_extensions}"
            ) from error

    def _extract_pdf(self, source_path: Path) -> list[ExtractedTextBlock]:
        """按 PDF 文本块提取，并保留从 1 开始的页码。"""

        blocks: list[ExtractedTextBlock] = []
        with pymupdf.open(source_path) as document:
            for page_number, page in enumerate(document, start=1):
                # blocks 按页面阅读顺序排序，能比整页文本更好地保留自然段边界。
                page_blocks = sorted(page.get_text("blocks"), key=lambda item: (item[1], item[0]))
                for page_block in page_blocks:
                    text = self._normalize_text(page_block[4])
                    if text:
                        blocks.append(
                            ExtractedTextBlock(
                                text=text,
                                page_number=page_number,
                            )
                        )
        return blocks

    def _extract_docx(self, source_path: Path) -> list[ExtractedTextBlock]:
        """读取 DOCX OpenXML 段落与标题样式，不依赖额外的 python-docx 包。"""

        namespace = {"w": self._WORD_NAMESPACE}
        paragraph_tag = f"{{{self._WORD_NAMESPACE}}}p"
        text_tag = f"{{{self._WORD_NAMESPACE}}}t"
        style_tag = f"{{{self._WORD_NAMESPACE}}}pStyle"
        style_value_key = f"{{{self._WORD_NAMESPACE}}}val"

        try:
            with zipfile.ZipFile(source_path) as archive:
                document_xml = archive.read("word/document.xml")
        except (KeyError, zipfile.BadZipFile) as error:
            raise KnowledgeTextExtractionError("DOCX 文件结构无效") from error

        try:
            document_root = ElementTree.fromstring(document_xml)
        except ElementTree.ParseError as error:
            raise KnowledgeTextExtractionError("DOCX 文档 XML 解析失败") from error

        blocks: list[ExtractedTextBlock] = []
        heading_stack: list[str | None] = [None] * 6
        for paragraph in document_root.iter(paragraph_tag):
            text = self._normalize_text("".join(
                node.text or "" for node in paragraph.iter(text_tag)
            ))
            if not text:
                continue

            style_node = paragraph.find(".//w:pPr/w:pStyle", namespace)
            style_id = style_node.get(style_value_key, "") if style_node is not None else ""
            heading_level = self._parse_docx_heading_level(style_id)
            if heading_level is not None:
                heading_stack[heading_level - 1] = text
                for index in range(heading_level, len(heading_stack)):
                    heading_stack[index] = None
                continue

            section_path = self._build_section_path(heading_stack)
            blocks.append(ExtractedTextBlock(text=text, section_path=section_path))
        return blocks

    def _extract_markdown(self, source_path: Path) -> list[ExtractedTextBlock]:
        """按 ATX 标题与空行段落提取 Markdown 文本。"""

        try:
            source_text = source_path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as error:
            raise KnowledgeTextExtractionError("Markdown 文件不是 UTF-8 编码") from error

        return self._extract_heading_paragraphs(source_text, parse_headings=True)

    def _extract_txt(self, source_path: Path) -> list[ExtractedTextBlock]:
        """按空行分段提取纯文本，不把普通井号文本误识别为标题。"""

        try:
            source_text = source_path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as error:
            raise KnowledgeTextExtractionError("TXT 文件不是 UTF-8 编码") from error

        return self._extract_heading_paragraphs(source_text, parse_headings=False)

    def _extract_heading_paragraphs(
        self,
        source_text: str,
        *,
        parse_headings: bool,
    ) -> list[ExtractedTextBlock]:
        """将 Markdown/TXT 按空行切为段落，并为 Markdown 附加标题路径。"""

        blocks: list[ExtractedTextBlock] = []
        paragraph_lines: list[str] = []
        heading_stack: list[str | None] = [None] * 6
        in_code_block = False

        def flush_paragraph() -> None:
            text = self._normalize_text("\n".join(paragraph_lines))
            paragraph_lines.clear()
            if text:
                blocks.append(
                    ExtractedTextBlock(
                        text=text,
                        section_path=self._build_section_path(heading_stack),
                    )
                )

        for raw_line in source_text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            stripped_line = raw_line.strip()
            if parse_headings and stripped_line.startswith("```"):
                in_code_block = not in_code_block

            heading_match = (
                self._MARKDOWN_HEADING_PATTERN.match(stripped_line)
                if parse_headings and not in_code_block
                else None
            )
            if heading_match:
                flush_paragraph()
                heading_level = len(heading_match.group(1))
                heading_stack[heading_level - 1] = heading_match.group(2).strip()
                for index in range(heading_level, len(heading_stack)):
                    heading_stack[index] = None
                continue

            if not stripped_line:
                flush_paragraph()
                continue
            paragraph_lines.append(raw_line)
        flush_paragraph()
        return blocks

    @staticmethod
    def _normalize_extension(file_type: str) -> str:
        normalized_file_type = file_type.strip().lower()
        if not normalized_file_type:
            return ""
        return (
            normalized_file_type
            if normalized_file_type.startswith(".")
            else f".{normalized_file_type}"
        )

    @staticmethod
    def _normalize_text(value: str) -> str:
        """统一换行、去除行首尾空白，但保留段内的换行和列表结构。"""

        normalized_lines = [
            re.sub(r"[ \t]+", " ", line).strip()
            for line in value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        ]
        return "\n".join(normalized_lines).strip()

    @staticmethod
    def _parse_docx_heading_level(style_id: str) -> int | None:
        normalized_style_id = style_id.lower().replace(" ", "")
        # Word 的内置样式 ID 通常是 Heading1；部分本地化或生成工具会写成
        # 标题1、heading_1 等形式，因此兼容这些常见表示。
        match = re.search(r"(?:heading|标题)[_-]?([1-6])$", normalized_style_id)
        return int(match.group(1)) if match else None

    @staticmethod
    def _build_section_path(heading_stack: list[str | None]) -> str | None:
        sections = [heading for heading in heading_stack if heading]
        return " > ".join(sections) if sections else None
