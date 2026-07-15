"""知识库文本清洗与切片预览测试。"""

import pytest

from services.knowledge_preview_service import KnowledgePreviewService
from services.knowledge_text_processing import KnowledgeTextProcessingConfig


class FakeUploadFile:
    """满足预览服务所需的最小上传文件接口。"""

    def __init__(self, filename: str, content: bytes):
        self.filename = filename
        self.content = content

    async def read(self, size: int = -1) -> bytes:
        return self.content


@pytest.mark.asyncio
async def test_preview_cleans_metadata_and_contact_information_without_persistence():
    config = KnowledgeTextProcessingConfig.from_mapping(
        {
            "cleaning": {
                "normalize_whitespace": True,
                "remove_urls_and_emails": True,
                "remove_blockquote_metadata": True,
            },
            "chunking": {"max_characters": 80, "overlap_characters": 10},
        }
    )
    result = await KnowledgePreviewService().preview(
        source=FakeUploadFile(
            "制度.md",
            (
                "# 制度\n\n> 这是样例说明\n\n## 休假\n\n"
                "请访问 https://example.com 或联系 hr@example.com。员工年假需提前申请。"
            ).encode(),
        ),
        document_title="员工休假制度",
        processing_config=config,
    )

    assert result.raw_block_count == 2
    assert result.cleaned_block_count == 1
    assert result.chunk_count == 1
    assert result.chunks[0].section_path == "制度 > 休假"
    assert "这是样例说明" not in result.chunks[0].content
    assert "https://example.com" not in result.chunks[0].content
    assert "hr@example.com" not in result.chunks[0].content
    assert "[链接已移除]" in result.chunks[0].content
    assert result.processing_config.to_dict() == config.to_dict()


def test_processing_config_rejects_overlap_larger_than_chunk():
    with pytest.raises(ValueError, match="overlap_characters"):
        KnowledgeTextProcessingConfig.from_mapping(
            {"chunking": {"max_characters": 100, "overlap_characters": 100}}
        )
