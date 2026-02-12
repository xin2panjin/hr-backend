#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from datetime import datetime, timezone, timedelta
import re


def datetime_to_iso8601_beijing(dt: datetime) -> str:
    """
    将datetime对象转换为ISO-8601格式字符串（北京时间，UTC+8）
    参数:
        dt: datetime对象，可以是naive或aware datetime
    返回:
        ISO-8601格式字符串，如：2022-11-27T00:00:00+08:00
    """
    # 定义北京时区（UTC+8）
    beijing_tz = timezone(timedelta(hours=8))

    # 如果datetime是naive（没有时区信息），假设它是本地时间并转换为UTC+8
    if dt.tzinfo is None:
        # 将naive datetime转换为aware datetime（UTC+8）
        dt_beijing = dt.replace(tzinfo=beijing_tz)
    else:
        # 如果datetime已经有时区信息，转换为UTC+8
        dt_beijing = dt.astimezone(beijing_tz)

    # 转换为ISO-8601格式字符串
    # 去除微秒，确保格式符合 API 要求
    return dt_beijing.replace(microsecond=0).isoformat()


def iso8601_to_datetime_beijing(iso_str: str) -> datetime:
    """
    将ISO-8601格式字符串转换为北京时间（UTC+8）的datetime对象

    参数:
        iso_str: ISO-8601格式字符串，支持以下格式：
                 - 带时区偏移: "2022-11-27T08:30:00+08:00"
                 - UTC标记: "2022-11-27T00:30:00Z"
                 - 无时区（naive）: "2022-11-27T08:30:00"（视为北京时间）

    返回:
        带时区信息的datetime对象（固定为UTC+8）

    异常:
        ValueError: 当输入字符串格式无效时抛出
    """
    # 1. 标准化输入：将末尾的'Z'替换为'+00:00'以便解析
    normalized_str = iso_str.strip()
    if normalized_str.endswith('Z'):
        normalized_str = normalized_str[:-1] + '+00:00'

    # 2. 处理微秒部分可能缺少补零的情况（Python 3.11+ 支持，但为兼容性处理）
    # 例如: "2022-11-27T08:30:00.1+08:00" -> 需要补零到6位
    # 使用正则匹配微秒部分并补零
    normalized_str = re.sub(
        r'(\.\d{1,6})(?![\d:])',
        lambda m: m.group(1) + '0' * (6 - len(m.group(1)) + 1),
        normalized_str
    )

    # 3. 解析ISO字符串
    try:
        dt = datetime.fromisoformat(normalized_str)
    except ValueError as e:
        # 尝试更宽松的解析（处理空格分隔等情况）
        try:
            # 替换空格为'T'以支持"2022-11-27 08:30:00"格式
            if ' ' in normalized_str and 'T' not in normalized_str:
                normalized_str = normalized_str.replace(' ', 'T', 1)
            dt = datetime.fromisoformat(normalized_str)
        except Exception:
            raise ValueError(f"无法解析ISO 8601字符串: '{iso_str}'。错误: {e}")

    # 4. 定义北京时区
    beijing_tz = timezone(timedelta(hours=8))

    # 5. 时区处理
    if dt.tzinfo is None:
        # naive datetime：视为北京时间（不改变时间数值，仅附加时区）
        dt = dt.replace(tzinfo=beijing_tz)
    else:
        # aware datetime：转换为北京时间（保持同一时刻，调整时间数值）
        dt = dt.astimezone(beijing_tz)

    return dt


# ==================== 测试用例 ====================
if __name__ == "__main__":
    print("=" * 60)
    print("ISO 8601 ↔ 北京时间 datetime 双向转换测试")
    print("=" * 60)

    # 测试用例集合
    test_cases = [
        # (输入字符串, 期望的北京时间表示)
        ("2022-11-27T08:30:00+08:00", "2022-11-27 08:30:00+08:00"),
        ("2022-11-27T00:30:00Z", "2022-11-27 08:30:00+08:00"),  # UTC转北京时间
        ("2022-11-27T00:30:00+00:00", "2022-11-27 08:30:00+08:00"),  # 明确UTC偏移
        ("2022-11-27T08:30:00", "2022-11-27 08:30:00+08:00"),  # naive视为北京时间
        ("2022-11-27T15:45:30.123456+08:00", "2022-11-27 15:45:30.123456+08:00"),
        ("2022-11-27 09:00:00", "2022-11-27 09:00:00+08:00"),  # 空格分隔格式
        ("2026-02-13T10:00:00Z", "2026-02-13 18:00:00+08:00"),  # 面试场景测试
    ]

    for iso_str, expected in test_cases:
        try:
            # 转换：字符串 → datetime
            dt = iso8601_to_datetime_beijing(iso_str)

            # 验证：datetime → 字符串（使用您原有的函数）
            roundtrip_iso = datetime_to_iso8601_beijing(dt)

            # 格式化输出用于比较
            dt_formatted = dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + dt.strftime("%z")
            dt_formatted = f"{dt_formatted[:-2]}:{dt_formatted[-2:]}"  # 格式化时区为+08:00

            # 检查是否符合预期
            status = "✅" if dt_formatted == expected else "❌"
            print(f"{status} 输入: {iso_str:30s} → 转换结果: {dt_formatted:30s} (期望: {expected})")

            # 双向验证
            if dt_formatted == expected:
                print(f"   ↳ 双向验证: '{iso_str}' → datetime → '{roundtrip_iso}'")
        except Exception as e:
            print(f"❌ 输入: {iso_str:30s} → 错误: {e}")
        print("-" * 60)

    # 边界测试：无效格式
    print("\n=== 边界测试：无效格式 ===")
    invalid_cases = ["invalid", "2022-13-01T00:00:00", "2022-11-27T25:00:00"]
    for case in invalid_cases:
        try:
            iso8601_to_datetime_beijing(case)
            print(f"❌ 本应失败的测试通过: {case}")
        except ValueError as e:
            print(f"✅ 正确捕获错误 ({case}): {str(e)[:50]}...")

    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)