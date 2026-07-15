"""生成智能 HR 人才库检索评测用合成简历 PDF 与清单。

用法：
    python scripts/generate_synthetic_test_resumes.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.synthetic_resumes.data import RESUMES  # noqa: E402

OUTPUT_DIR = ROOT / "output" / "pdf" / "test_resumes" / "synthetic"
MANIFEST_JSON = ROOT / "output" / "pdf" / "test_resumes" / "synthetic_resume_manifest.json"
MANIFEST_MD = ROOT / "output" / "pdf" / "test_resumes" / "synthetic_resume_manifest.md"

FONT_CANDIDATES = [
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
]


def _register_font() -> str:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            try:
                pdfmetrics.registerFont(TTFont("SynthResumeFont", path))
                return "SynthResumeFont"
            except Exception:
                continue
    raise RuntimeError("未找到可用的中文字体，请安装 Arial Unicode 或 Songti")


def _styles(font_name: str) -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "name": ParagraphStyle(
            "Name",
            parent=base["Normal"],
            fontName=font_name,
            fontSize=18,
            leading=24,
            spaceAfter=2 * mm,
        ),
        "subtitle": ParagraphStyle(
            "Subtitle",
            parent=base["Normal"],
            fontName=font_name,
            fontSize=10,
            leading=14,
            spaceAfter=3 * mm,
        ),
        "meta": ParagraphStyle(
            "Meta",
            parent=base["Normal"],
            fontName=font_name,
            fontSize=9,
            leading=13,
            spaceAfter=1 * mm,
        ),
        "section": ParagraphStyle(
            "Section",
            parent=base["Normal"],
            fontName=font_name,
            fontSize=11,
            leading=16,
            spaceBefore=3.5 * mm,
            spaceAfter=1.5 * mm,
        ),
        "job_title": ParagraphStyle(
            "JobTitle",
            parent=base["Normal"],
            fontName=font_name,
            fontSize=9.5,
            leading=13,
            spaceBefore=1.5 * mm,
            spaceAfter=0.5 * mm,
        ),
        "body": ParagraphStyle(
            "Body",
            parent=base["Normal"],
            fontName=font_name,
            fontSize=9,
            leading=13,
            spaceAfter=0.8 * mm,
        ),
        "bullet": ParagraphStyle(
            "Bullet",
            parent=base["Normal"],
            fontName=font_name,
            fontSize=9,
            leading=13,
            leftIndent=4 * mm,
            spaceAfter=0.6 * mm,
        ),
    }


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def build_story(resume: dict, styles: dict[str, ParagraphStyle]) -> list:
    story: list = []
    story.append(Paragraph(_escape(resume["name"]), styles["name"]))
    story.append(Paragraph(_escape(resume["headline"]), styles["subtitle"]))

    meta_lines = [
        f"应聘岗位：{resume['target_position']}",
        f"工作年限：{resume['years']}年",
        f"期望城市：{resume['city']}",
        f"电话：{resume['phone']}",
        f"邮箱：{resume['email']}",
        f"到岗时间：{resume['availability']}",
    ]
    for line in meta_lines:
        story.append(Paragraph(_escape(line), styles["meta"]))

    story.append(Paragraph("个人优势", styles["section"]))
    for item in resume["highlights"]:
        story.append(Paragraph(f"● {_escape(item)}", styles["bullet"]))

    story.append(Paragraph("工作经历", styles["section"]))
    for job in resume["experiences"]:
        header = f"{job['company']}｜{job['title']} {job['period']}"
        story.append(Paragraph(_escape(header), styles["job_title"]))
        if job.get("summary"):
            story.append(Paragraph(_escape(job["summary"]), styles["body"]))
        for bullet in job["bullets"]:
            story.append(Paragraph(f"● {_escape(bullet)}", styles["bullet"]))

    if resume.get("projects"):
        story.append(Paragraph("项目经历", styles["section"]))
        for project in resume["projects"]:
            header = f"{project['name']} {project['period']}"
            story.append(Paragraph(_escape(header), styles["job_title"]))
            if project.get("summary"):
                story.append(Paragraph(_escape(project["summary"]), styles["body"]))
            for bullet in project["bullets"]:
                story.append(Paragraph(f"● {_escape(bullet)}", styles["bullet"]))

    edu = resume["education"]
    story.append(Paragraph("教育背景", styles["section"]))
    story.append(
        Paragraph(
            _escape(f"{edu['school']}｜{edu['major']} {edu['degree']} {edu['period']}"),
            styles["job_title"],
        )
    )
    if edu.get("note"):
        story.append(Paragraph(_escape(edu["note"]), styles["body"]))
    for bullet in edu.get("bullets", []):
        story.append(Paragraph(f"● {_escape(bullet)}", styles["bullet"]))

    story.append(Paragraph("技能标签", styles["section"]))
    story.append(Paragraph(_escape("、".join(resume["skills"])), styles["body"]))

    story.append(Paragraph("其他信息", styles["section"]))
    for item in resume["other"]:
        story.append(Paragraph(f"● {_escape(item)}", styles["bullet"]))

    story.append(Spacer(1, 2 * mm))
    return story


def render_pdf(resume: dict, output_path: Path, styles: dict[str, ParagraphStyle]) -> None:
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=f"{resume['name']} - {resume['synthetic_key']}",
        author="synthetic-test-resumes",
    )
    doc.build(build_story(resume, styles))


def build_manifest_entry(resume: dict, filename: str) -> dict:
    return {
        "synthetic_key": resume["synthetic_key"],
        "filename": filename,
        "name": resume["name"],
        "category": resume["category"],
        "tags": resume["tags"],
        "status": resume["status"],
        "department": resume["department"],
        "target_position": resume["target_position"],
        "years": resume["years"],
        "city": resume["city"],
        "relevant_for": resume.get("relevant_for", []),
        "distractor_for": resume.get("distractor_for", []),
        "eval_notes": resume.get("eval_notes", ""),
    }


def write_manifest_md(entries: list[dict]) -> None:
    lines = [
        "# 合成测试简历清单",
        "",
        "本清单用于人才库检索评测。不直接绑定真实候选人 ID，导入后再映射 `synthetic_key`。",
        "",
        "## 分布校验",
        "",
    ]

    from collections import Counter

    cat = Counter(e["category"] for e in entries)
    status = Counter(e["status"] for e in entries)
    dept = Counter(e["department"] for e in entries)

    lines.append("### 类别")
    for k, v in cat.items():
        lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("### 状态")
    for k, v in status.items():
        lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("### 部门")
    for k, v in dept.items():
        lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("## 明细")
    lines.append("")

    for e in entries:
        lines.extend(
            [
                f"### {e['synthetic_key']}",
                "",
                f"- 文件: `{e['filename']}`",
                f"- 姓名: {e['name']}",
                f"- 类别: {e['category']}",
                f"- 标签: {', '.join(e['tags'])}",
                f"- 状态: {e['status']}",
                f"- 部门: {e['department']}",
                f"- 可作为相关样本: {' / '.join(e['relevant_for']) or '（无）'}",
                f"- 可作为干扰样本: {' / '.join(e['distractor_for']) or '（无）'}",
                f"- 评测说明: {e['eval_notes']}",
                "",
            ]
        )

    MANIFEST_MD.write_text("\n".join(lines), encoding="utf-8")


def _resume_body_blob(resume: dict) -> str:
    """仅拼接会写入 PDF 的字段，用于空结果技能词校验。"""
    parts: list[str] = [
        resume.get("headline", ""),
        resume.get("target_position", ""),
        " ".join(resume.get("highlights", [])),
        " ".join(resume.get("skills", [])),
        " ".join(resume.get("other", [])),
    ]
    for job in resume.get("experiences", []):
        parts.extend([job.get("company", ""), job.get("title", ""), job.get("summary", "")])
        parts.extend(job.get("bullets", []))
    for project in resume.get("projects", []):
        parts.extend([project.get("name", ""), project.get("summary", "")])
        parts.extend(project.get("bullets", []))
    edu = resume.get("education", {})
    parts.extend(
        [
            edu.get("school", ""),
            edu.get("major", ""),
            edu.get("note", ""),
            " ".join(edu.get("bullets", [])),
        ]
    )
    return "\n".join(parts)


def validate_distribution(resumes: list[dict]) -> None:
    from collections import Counter

    assert len(resumes) == 50, f"期望 50 份，实际 {len(resumes)}"
    keys = [r["synthetic_key"] for r in resumes]
    assert len(keys) == len(set(keys)), "synthetic_key 有重复"

    status = Counter(r["status"] for r in resumes)
    assert status["已投递"] == 15
    assert status["AI筛选通过"] == 10
    assert status["待面试"] == 10
    assert status["AI筛选未通过"] == 10
    assert status["已入职"] == 5

    dept = Counter(r["department"] for r in resumes)
    assert dept["技术部"] == 16
    assert dept["算法/AI平台"] == 14
    assert dept["数据/风控"] == 10
    assert dept["产品部"] == 4
    assert dept["人力资源部"] == 3
    assert dept["运营部"] == 3

    forbidden = ["量子计算编译器", "芯片 RTL 验证", "临床手术机器人"]
    body = "\n".join(_resume_body_blob(r) for r in resumes)
    for term in forbidden:
        assert term not in body, f"禁止在简历正文出现空结果查询技能词: {term}"
    # 保留近似词，便于检验拒答阈值
    assert "编译优化" in body and "高性能计算" in body


def main() -> None:
    font_name = _register_font()
    styles = _styles(font_name)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    validate_distribution(RESUMES)

    entries: list[dict] = []
    for idx, resume in enumerate(RESUMES, start=1):
        filename = f"{idx:02d}_{resume['synthetic_key']}.pdf"
        path = OUTPUT_DIR / filename
        render_pdf(resume, path, styles)
        entries.append(build_manifest_entry(resume, filename))
        print(f"generated {filename}")

    MANIFEST_JSON.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_manifest_md(entries)
    print(f"manifest -> {MANIFEST_JSON}")
    print(f"manifest -> {MANIFEST_MD}")
    print(f"pdf dir   -> {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
