"""结构化分块器：门店文档按「问题类别 + 操作步骤 + 注意事项」解析为结构化 Chunk。

文档约定为类 Markdown 格式（data/gen_docs.py 按此格式生成）：

    # 问题类别：设备报修流程
    ## 操作步骤
    1. 打开企业微信工作台，进入「设备报修」
    2. ...
    ## 注意事项
    - 保修期内设备请先联系厂商
    - ...

每个文件可包含多个「问题类别」小节，分块器按小节切分，
并把类别、步骤、注意事项作为结构化元数据挂到 Chunk 上。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List

from ..config import settings

SECTION_TITLES = ("操作步骤", "注意事项", "常见问题")


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    category: str                       # 问题类别（用于意图路由与检索过滤）
    steps: List[str] = field(default_factory=list)
    notices: List[str] = field(default_factory=list)
    faqs: List[str] = field(default_factory=list)
    text: str = ""                      # 复合检索文本
    keywords: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _parse_sections(lines: List[str]):
    """把按 '## 标题' 组织的内容解析成 {section: [行]}。"""
    sections: dict = {}
    current = "正文"
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("##"):
            current = line.lstrip("#").strip()
            sections.setdefault(current, [])
        else:
            sections.setdefault(current, []).append(line)
    return sections


def _split_category(lines: List[str]):
    """按顶层标题（'# '，而非 '## '）切分：返回 [(类别, 展示名, 该类别下的行列表)]。"""
    blocks: List[tuple] = []
    current_title = None
    current_lines: List[str] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("# "):  # 顶层标题 = 一个问题类别
            title = line[2:].strip()
            if current_title is None:
                current_title = title
            else:
                blocks.append((current_title, current_lines))
                current_title = title
                current_lines = []
        elif current_title is None:
            continue  # 头部非标题行忽略
        else:
            current_lines.append(line)
    if current_title is not None:
        blocks.append((current_title, current_lines))
    return blocks


def _normalize_category(title: str) -> tuple:
    """从标题解析 (category, display_title)。
    '# 问题类别：设备报修：收银机死机处理' → ('设备报修', '设备报修：收银机死机处理')
    """
    raw = title.replace("问题类别", "").strip().lstrip("：:").strip()
    parts = re.split(r"[：:]", raw, maxsplit=1)
    if len(parts) == 2 and parts[0].strip():
        category = parts[0].strip()
        display = f"{category}：{parts[1].strip()}"
    else:
        category = raw
        display = raw
    return category, display


def _extract_keywords(text: str, top_n: int = 8) -> List[str]:
    """轻量关键词提取：按常用词表过滤后的字符二元组/词频。"""
    stop = set("的了一是在不有和就人都吗吧呢啊我你他这家门店请如需进行以下操作注意事项问题类别如果否则")
    # 优先匹配中文词（2-6 字连续片段）太碎，直接统计 2-4 字窗口词频
    freq: dict = {}
    chars = [c for c in text if "\u4e00" <= c <= "\u9fff"]
    for n in (2, 3, 4):
        for i in range(len(chars) - n + 1):
            w = "".join(chars[i:i + n])
            if any(s in w for s in stop):
                continue
            freq[w] = freq.get(w, 0) + 1
    return [w for w, _ in sorted(freq.items(), key=lambda x: -x[1])[:top_n]]


class StructuredChunker:
    """解析门店文档目录 → 结构化 Chunk 列表。"""

    def __init__(self, docs_dir: Path | None = None):
        self.docs_dir = docs_dir or settings.raw_docs_dir

    def parse_file(self, path: Path) -> List[Chunk]:
        text = path.read_text(encoding="utf-8")
        lines = [l for l in text.splitlines() if l.strip()]
        chunks: List[Chunk] = []
        for idx, (title, body) in enumerate(_split_category(lines)):
            sections = _parse_sections(body)
            steps = sections.get("操作步骤", [])
            notices = sections.get("注意事项", [])
            faqs = sections.get("常见问题", [])
            category, display_title = _normalize_category(title)
            composite = "\n".join(
                [f"问题类别：{display_title}"]
                + ([f"操作步骤：{' '.join(steps)}"] if steps else [])
                + ([f"注意事项：{' '.join(notices)}"] if notices else [])
                + ([f"常见问题：{' '.join(faqs)}"] if faqs else [])
            )
            chunks.append(Chunk(
                chunk_id=f"{path.stem}-c{idx}",
                doc_id=path.stem,
                category=category,
                steps=steps,
                notices=notices,
                faqs=faqs,
                text=composite,
                keywords=_extract_keywords(composite),
            ))
        return chunks

    def parse_dir(self) -> List[Chunk]:
        chunks: List[Chunk] = []
        for path in sorted(self.docs_dir.glob("*.md")):
            chunks.extend(self.parse_file(path))
        return chunks


def chunk_documents(docs_dir: Path | None = None) -> List[Chunk]:
    return StructuredChunker(docs_dir).parse_dir()
