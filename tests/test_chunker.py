"""结构化分块器单测。"""
from __future__ import annotations

from pathlib import Path

from app.rag.chunker import StructuredChunker


def _write_doc(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "sample.md"
    p.write_text(content, encoding="utf-8")
    return p


def test_parse_single_category(tmp_path):
    p = _write_doc(tmp_path, "# 问题类别：设备报修：收银机死机处理\n"
                              "## 操作步骤\n1. 长按电源键重启\n2. 提交报修\n"
                              "## 注意事项\n- 严禁直接拔电源")
    chunks = StructuredChunker(tmp_path).parse_file(p)
    assert len(chunks) == 1
    c = chunks[0]
    assert c.category == "设备报修"
    assert len(c.steps) == 2
    assert len(c.notices) == 1
    assert "报修" in c.text


def test_parse_multi_category(tmp_path):
    p = _write_doc(tmp_path, "# 问题类别：设备报修：A\n## 操作步骤\n1. x\n"
                              "# 问题类别：物料库存：B\n## 操作步骤\n1. y\n## 注意事项\n- z")
    chunks = StructuredChunker(tmp_path).parse_file(p)
    assert len(chunks) == 2
    assert chunks[0].category == "设备报修" and chunks[1].category == "物料库存"


def test_keywords_extracted(tmp_path):
    p = _write_doc(tmp_path, "# 问题类别：促销政策：满减活动\n## 操作步骤\n1. 满100减20\n## 注意事项\n- 不叠加")
    chunks = StructuredChunker(tmp_path).parse_file(p)
    assert len(chunks[0].keywords) > 0
