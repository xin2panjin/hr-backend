"""知识库文本清洗与结构化切片的纯处理能力。

本模块不访问数据库、文件系统或外部模型。预览与异步索引任务共用它，
从而保证管理员在页面看到的切片就是随后会被写入知识库的切片。
"""

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Iterable, Mapping

from services.knowledge_text_extractor import ExtractedTextBlock


class KnowledgeChunkingStrategy(StrEnum):
    """知识库支持的正文切分策略。"""

    STRUCTURED_BUILTIN = "structured_builtin"
    FIXED_LENGTH = "fixed_length"
    CUSTOM_CHARACTER = "custom_character"
    LANGCHAIN_RECURSIVE = "langchain_recursive"
    # 仅用于回放旧索引任务的配置快照，不在前端暴露。
    LEGACY_CUSTOM_SEPARATOR = "custom_separator"


# 使用中文常见标点作为递归兜底，避免直接沿用偏英文的默认分隔符。
DEFAULT_RECURSIVE_SEPARATORS = (
    "\n\n", "\n", "。", "！", "？", "；", ";", "，", ",", " ", "",
)
DEFAULT_CUSTOM_SEPARATOR = "。"


@dataclass(frozen=True, slots=True)
class KnowledgeTextCleaningConfig:
    """文本清洗配置；默认值保持当前索引行为。"""

    normalize_whitespace: bool = True
    remove_urls_and_emails: bool = False
    remove_blockquote_metadata: bool = False


@dataclass(frozen=True, slots=True)
class KnowledgeChunkingConfig:
    """结构化切片配置。"""

    max_characters: int = 500
    overlap_characters: int = 80
    strategy: KnowledgeChunkingStrategy = KnowledgeChunkingStrategy.STRUCTURED_BUILTIN
    custom_separator: str = DEFAULT_CUSTOM_SEPARATOR
    recursive_separators: tuple[str, ...] = DEFAULT_RECURSIVE_SEPARATORS
    # 兼容已经写入任务表的旧版递归分隔符配置，避免重试时改变切片结果。
    legacy_custom_separators: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class KnowledgeTextProcessingConfig:
    """一次预览或索引任务使用的完整、可序列化处理配置。"""

    cleaning: KnowledgeTextCleaningConfig = KnowledgeTextCleaningConfig()
    chunking: KnowledgeChunkingConfig = KnowledgeChunkingConfig()

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any] | None,
    ) -> "KnowledgeTextProcessingConfig":
        """从 API 或任务元数据恢复配置，并统一校验范围。"""

        raw_value = value or {}
        cleaning_value = raw_value.get("cleaning") or {}
        chunking_value = raw_value.get("chunking") or {}
        if not isinstance(cleaning_value, Mapping) or not isinstance(chunking_value, Mapping):
            raise ValueError("文本处理配置格式错误")

        cleaning = KnowledgeTextCleaningConfig(
            normalize_whitespace=cls._require_bool(
                cleaning_value.get("normalize_whitespace", True),
                "normalize_whitespace",
            ),
            remove_urls_and_emails=cls._require_bool(
                cleaning_value.get("remove_urls_and_emails", False),
                "remove_urls_and_emails",
            ),
            remove_blockquote_metadata=cls._require_bool(
                cleaning_value.get("remove_blockquote_metadata", False),
                "remove_blockquote_metadata",
            ),
        )
        max_characters = cls._require_int(
            chunking_value.get("max_characters", 500),
            "max_characters",
        )
        overlap_characters = cls._require_int(
            chunking_value.get("overlap_characters", 80),
            "overlap_characters",
        )
        raw_strategy = chunking_value.get(
            "strategy", KnowledgeChunkingStrategy.STRUCTURED_BUILTIN
        )
        try:
            strategy = KnowledgeChunkingStrategy(raw_strategy)
        except (TypeError, ValueError) as error:
            supported_strategies = ", ".join(
                item.value
                for item in KnowledgeChunkingStrategy
                if item != KnowledgeChunkingStrategy.LEGACY_CUSTOM_SEPARATOR
            )
            raise ValueError(f"strategy 必须为以下之一：{supported_strategies}") from error
        custom_separator = cls._parse_custom_separator(
            chunking_value.get("custom_separator", DEFAULT_CUSTOM_SEPARATOR)
        )
        recursive_separators = cls._parse_recursive_separators(
            chunking_value.get("recursive_separators", DEFAULT_RECURSIVE_SEPARATORS)
        )
        legacy_custom_separators = (
            cls._parse_legacy_custom_separators(chunking_value.get("custom_separators"))
            if strategy == KnowledgeChunkingStrategy.LEGACY_CUSTOM_SEPARATOR
            else None
        )
        return cls(
            cleaning=cleaning,
            chunking=KnowledgeChunkingConfig(
                max_characters=max_characters,
                overlap_characters=overlap_characters,
                strategy=strategy,
                custom_separator=custom_separator,
                recursive_separators=recursive_separators,
                legacy_custom_separators=legacy_custom_separators,
            ),
        ).validate()

    def validate(self) -> "KnowledgeTextProcessingConfig":
        """校验配置，避免产生过小、过大或无限循环的切片。"""

        if not 50 <= self.chunking.max_characters <= 2000:
            raise ValueError("max_characters 必须在 50 到 2000 之间")
        if not 0 <= self.chunking.overlap_characters < self.chunking.max_characters:
            raise ValueError("overlap_characters 必须大于等于 0 且小于 max_characters")
        if self.chunking.strategy == KnowledgeChunkingStrategy.CUSTOM_CHARACTER:
            self._validate_custom_separator(self.chunking.custom_separator)
        if self.chunking.strategy == KnowledgeChunkingStrategy.LANGCHAIN_RECURSIVE:
            self._validate_recursive_separators(self.chunking.recursive_separators)
        if self.chunking.strategy == KnowledgeChunkingStrategy.LEGACY_CUSTOM_SEPARATOR:
            self._validate_legacy_custom_separators(self.chunking.legacy_custom_separators)
        return self

    def to_dict(self) -> dict[str, dict[str, bool | int | str | list[str]]]:
        """生成可直接写入 JSON 任务元数据的稳定结构。"""

        chunking: dict[str, bool | int | str | list[str]] = {
            "max_characters": self.chunking.max_characters,
            "overlap_characters": self.chunking.overlap_characters,
            "strategy": self.chunking.strategy.value,
            "custom_separator": self.chunking.custom_separator,
            "recursive_separators": list(self.chunking.recursive_separators),
        }
        if self.chunking.strategy == KnowledgeChunkingStrategy.LEGACY_CUSTOM_SEPARATOR:
            chunking["custom_separators"] = list(
                self.chunking.legacy_custom_separators or ()
            )
        else:
            chunking["custom_separator"] = self.chunking.custom_separator
        return {
            "cleaning": {
                "normalize_whitespace": self.cleaning.normalize_whitespace,
                "remove_urls_and_emails": self.cleaning.remove_urls_and_emails,
                "remove_blockquote_metadata": self.cleaning.remove_blockquote_metadata,
            },
            "chunking": chunking,
        }

    @staticmethod
    def _require_bool(value: Any, field_name: str) -> bool:
        if not isinstance(value, bool):
            raise ValueError(f"{field_name} 必须为布尔值")
        return value

    @staticmethod
    def _require_int(value: Any, field_name: str) -> int:
        # bool 是 int 的子类，必须单独排除，避免 True 被误认为 1。
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{field_name} 必须为整数")
        return value

    @staticmethod
    def _parse_custom_separator(value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("custom_separator 必须是字符串")
        return value

    @staticmethod
    def _parse_legacy_custom_separators(value: Any) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("custom_separators 必须是字符串数组")
        if any(not isinstance(item, str) for item in value):
            raise ValueError("custom_separators 必须是字符串数组")
        return tuple(value)

    @staticmethod
    def _parse_recursive_separators(value: Any) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("recursive_separators 必须是字符串数组")
        if any(not isinstance(item, str) for item in value):
            raise ValueError("recursive_separators 必须是字符串数组")
        return tuple(value)

    @staticmethod
    def _validate_custom_separator(separator: str) -> None:
        if not separator:
            raise ValueError("custom_separator 不能为空")
        if len(separator) > 20:
            raise ValueError("custom_separator 长度不能超过 20")

    @staticmethod
    def _validate_legacy_custom_separators(separators: tuple[str, ...] | None) -> None:
        if separators is None:
            raise ValueError("旧版 custom_separator 策略缺少 custom_separators")
        if not 1 <= len(separators) <= 20:
            raise ValueError("custom_separators 数量必须在 1 到 20 之间")
        for index, separator in enumerate(separators):
            if len(separator) > 20:
                raise ValueError("custom_separators 的单项长度不能超过 20")
            if not separator and index != len(separators) - 1:
                raise ValueError("custom_separators 的空字符串只能作为最后一个兜底分隔符")

    @staticmethod
    def _validate_recursive_separators(separators: tuple[str, ...]) -> None:
        if not 1 <= len(separators) <= 20:
            raise ValueError("recursive_separators 数量必须在 1 到 20 之间")
        for index, separator in enumerate(separators):
            if len(separator) > 20:
                raise ValueError("recursive_separators 的单项长度不能超过 20")
            if not separator and index != len(separators) - 1:
                raise ValueError("recursive_separators 的空字符串只能作为最后一个兜底分隔符")


class KnowledgeTextCleaner:
    """按配置清洗提取后的文本块，并保留章节和页码定位。"""

    _URL_PATTERN = re.compile(r"(?:https?://|www\.)[^\s<>]+", re.IGNORECASE)
    _EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)

    def clean(
        self,
        text_blocks: Iterable[ExtractedTextBlock],
        *,
        config: KnowledgeTextCleaningConfig,
    ) -> list[ExtractedTextBlock]:
        """返回非空的清洗结果，首段引用元数据可按需整体移除。"""

        cleaned_blocks: list[ExtractedTextBlock] = []
        removing_leading_metadata = config.remove_blockquote_metadata
        for block in text_blocks:
            cleaned_text = self._clean_text(block.text, config=config)
            if not cleaned_text:
                continue
            if removing_leading_metadata and self._is_blockquote_metadata(cleaned_text):
                continue
            removing_leading_metadata = False
            cleaned_blocks.append(
                ExtractedTextBlock(
                    text=cleaned_text,
                    page_number=block.page_number,
                    section_path=block.section_path,
                )
            )
        return cleaned_blocks

    def _clean_text(self, text: str, *, config: KnowledgeTextCleaningConfig) -> str:
        cleaned_text = text.replace("\r\n", "\n").replace("\r", "\n")
        if config.remove_urls_and_emails:
            cleaned_text = self._URL_PATTERN.sub("[链接已移除]", cleaned_text)
            cleaned_text = self._EMAIL_PATTERN.sub("[邮箱已移除]", cleaned_text)
        if config.normalize_whitespace:
            cleaned_text = "\n".join(
                re.sub(r"[ \t]+", " ", line).strip()
                for line in cleaned_text.split("\n")
                if line.strip()
            )
        return cleaned_text.strip()

    @staticmethod
    def _is_blockquote_metadata(text: str) -> bool:
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        return bool(lines) and all(line.startswith(">") for line in lines)


@dataclass(frozen=True, slots=True)
class StructuredKnowledgeChunk:
    """结构优先切片器生成的、可直接持久化的切片数据。"""

    chunk_index: int
    content: str
    content_hash: str
    token_count: int
    section_path: str | None
    page_number: int | None


class StructuredKnowledgeChunker:
    """按章节、页码和段落边界切分通用知识文档。"""

    def __init__(
        self,
        *,
        max_characters: int = 500,
        overlap_characters: int = 80,
        strategy: KnowledgeChunkingStrategy | str = KnowledgeChunkingStrategy.STRUCTURED_BUILTIN,
        custom_separator: str = DEFAULT_CUSTOM_SEPARATOR,
        recursive_separators: Iterable[str] = DEFAULT_RECURSIVE_SEPARATORS,
        legacy_custom_separators: Iterable[str] | None = None,
    ):
        normalized_strategy = KnowledgeChunkingStrategy(strategy)
        self.config = KnowledgeTextProcessingConfig(
            chunking=KnowledgeChunkingConfig(
                max_characters=max_characters,
                overlap_characters=overlap_characters,
                strategy=normalized_strategy,
                custom_separator=custom_separator,
                recursive_separators=tuple(recursive_separators),
                legacy_custom_separators=(
                    tuple(legacy_custom_separators)
                    if legacy_custom_separators is not None
                    else None
                ),
            )
        ).validate()
        self.max_characters = self.config.chunking.max_characters
        self.overlap_characters = self.config.chunking.overlap_characters

    @classmethod
    def from_config(cls, config: KnowledgeTextProcessingConfig) -> "StructuredKnowledgeChunker":
        """由完整配置创建切片器，避免预览和索引参数漂移。"""

        return cls(
            max_characters=config.chunking.max_characters,
            overlap_characters=config.chunking.overlap_characters,
            strategy=config.chunking.strategy,
            custom_separator=config.chunking.custom_separator,
            recursive_separators=config.chunking.recursive_separators,
            legacy_custom_separators=config.chunking.legacy_custom_separators,
        )

    def chunk(
        self,
        *,
        document_title: str,
        text_blocks: Iterable[ExtractedTextBlock],
    ) -> list[StructuredKnowledgeChunk]:
        """按连续的章节和页码分组后生成有重叠的结构化切片。"""

        normalized_title = document_title.strip()
        if not normalized_title:
            raise ValueError("document_title 不能为空")

        chunks: list[StructuredKnowledgeChunk] = []
        current_group: list[str] = []
        current_section_path: str | None = None
        current_page_number: int | None = None

        def flush_group() -> None:
            if not current_group:
                return
            source_text = "\n\n".join(current_group)
            for body_text in self._split_to_chunk_bodies(source_text):
                content = self._build_chunk_content(
                    document_title=normalized_title,
                    section_path=current_section_path,
                    body_text=body_text,
                )
                chunks.append(
                    StructuredKnowledgeChunk(
                        chunk_index=len(chunks),
                        content=content,
                        content_hash=self._calculate_content_hash(content),
                        token_count=self._estimate_token_count(content),
                        section_path=current_section_path,
                        page_number=current_page_number,
                    )
                )
            current_group.clear()

        for text_block in text_blocks:
            normalized_text = self._normalize_text(text_block.text)
            if not normalized_text:
                continue
            block_location = (text_block.section_path, text_block.page_number)
            current_location = (current_section_path, current_page_number)
            if current_group and block_location != current_location:
                flush_group()
            if not current_group:
                current_section_path, current_page_number = block_location
            current_group.append(normalized_text)
        flush_group()

        if not chunks:
            raise ValueError("无法从空文本块生成切片")
        return chunks

    def _split_to_chunk_bodies(self, source_text: str) -> list[str]:
        if self.config.chunking.strategy != KnowledgeChunkingStrategy.STRUCTURED_BUILTIN:
            return self._split_with_langchain(source_text)
        sentences = self._split_sentences(source_text)
        chunks: list[str] = []
        current_parts: list[str] = []
        current_length = 0
        for sentence in sentences:
            if len(sentence) > self.max_characters:
                if current_parts:
                    chunks.append("".join(current_parts).strip())
                    current_parts = []
                    current_length = 0
                chunks.extend(self._split_long_text(sentence))
                continue
            if current_parts and current_length + len(sentence) > self.max_characters:
                previous_chunk = "".join(current_parts).strip()
                chunks.append(previous_chunk)
                overlap = self._build_overlap(previous_chunk)
                if overlap and len(overlap) + len(sentence) <= self.max_characters:
                    current_parts = [overlap, sentence]
                    current_length = len(overlap) + len(sentence)
                else:
                    current_parts = [sentence]
                    current_length = len(sentence)
                continue
            current_parts.append(sentence)
            current_length += len(sentence)
        if current_parts:
            chunks.append("".join(current_parts).strip())
        return [chunk for chunk in chunks if chunk]

    def _split_with_langchain(self, source_text: str) -> list[str]:
        """以 LangChain splitter 切分一个已保留来源定位的结构文本组。"""

        try:
            from langchain_text_splitters import (
                CharacterTextSplitter,
                RecursiveCharacterTextSplitter,
            )
        except ImportError as error:  # pragma: no cover - 依赖由项目安装流程保证
            raise RuntimeError(
                "当前策略依赖 langchain-text-splitters，请先安装项目依赖"
            ) from error

        strategy = self.config.chunking.strategy
        common_options = {
            "chunk_size": self.max_characters,
            "chunk_overlap": self.overlap_characters,
            "length_function": len,
            "strip_whitespace": True,
        }
        if strategy == KnowledgeChunkingStrategy.FIXED_LENGTH:
            splitter = CharacterTextSplitter(separator="", **common_options)
        elif strategy == KnowledgeChunkingStrategy.CUSTOM_CHARACTER:
            splitter = CharacterTextSplitter(
                separator=self.config.chunking.custom_separator,
                keep_separator="end",
                **common_options,
            )
        elif strategy == KnowledgeChunkingStrategy.LANGCHAIN_RECURSIVE:
            splitter = RecursiveCharacterTextSplitter(
                separators=list(self.config.chunking.recursive_separators),
                **common_options,
            )
        elif strategy == KnowledgeChunkingStrategy.LEGACY_CUSTOM_SEPARATOR:
            splitter = RecursiveCharacterTextSplitter(
                separators=list(self.config.chunking.legacy_custom_separators or ()),
                **common_options,
            )
        else:  # 防御分支，确保新增策略不会静默使用错误实现。
            raise ValueError(f"不支持的切分策略：{strategy}")
        return [chunk for chunk in splitter.split_text(source_text) if chunk]

    def _split_long_text(self, text: str) -> list[str]:
        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = min(start + self.max_characters, len(text))
            chunks.append(text[start:end].strip())
            if end == len(text):
                break
            start = end - self.overlap_characters
        return [chunk for chunk in chunks if chunk]

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        return [sentence for sentence in re.split(r"(?<=[。！？!?；;])", text) if sentence.strip()]

    def _build_overlap(self, previous_chunk: str) -> str:
        return previous_chunk[-self.overlap_characters :] if self.overlap_characters else ""

    @staticmethod
    def _build_chunk_content(*, document_title: str, section_path: str | None, body_text: str) -> str:
        context_lines = [f"制度：{document_title}"]
        if section_path:
            context_lines.append(f"章节：{section_path}")
        context_lines.append(f"正文：{body_text}")
        return "\n".join(context_lines)

    @staticmethod
    def _calculate_content_hash(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _estimate_token_count(content: str) -> int:
        return len(re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9_]+|[^\s]", content))

    @staticmethod
    def _normalize_text(value: str) -> str:
        return "\n".join(
            line.strip()
            for line in value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
            if line.strip()
        )
