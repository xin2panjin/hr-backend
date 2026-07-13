"""招聘助手 SSE 路由的协议测试。"""

from routers.assistant_router import _format_sse


def test_format_sse_keeps_event_name_and_chinese_data():
    """路由输出必须是浏览器可识别的标准 SSE 帧。"""

    payload = _format_sse(
        "tool_start",
        {"tool": "search_talent_pool", "display": "正在检索人才库"},
    )

    assert payload == (
        'event: tool_start\n'
        'data: {"tool": "search_talent_pool", "display": "正在检索人才库"}\n\n'
    )
