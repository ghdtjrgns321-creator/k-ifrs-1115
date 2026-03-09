# app/ui/pinpoint_panel.py
# AI 답변 근거 패널.
#
# 본문: AI 답변에 인용된 문단만 표시 + 속한 섹션 제목으로 그룹핑
# 적용사례/QNA/감리사례: summary 임베딩 코사인 유사도 매칭 (토픽 무관)

import html
import re

import streamlit as st

from app.domain.summary_matcher import (
    match_findings_by_summary,
    match_ie_by_summary,
    match_qna_by_summary,
)
from app.domain.topic_content_map import TOPIC_CONTENT_MAP
from app.embeddings import embed_query_sync
from app.ui.components import _render_pdr_expander
from app.ui.db import _expand_para_range, fetch_docs_by_para_ids, fetch_parent_doc
from app.ui.doc_helpers import _build_self_ids, _get_doc_para_num
from app.ui.doc_renderers import _render_para_chips
from app.ui.text import _esc, _normalize_doc_content, clean_text
from app.ui.topic_browse import _format_desc_html

_DOC_IDX = {"counter": 4000}

# ── 문단 번호 추출 정규식 ─────────────────────────────────────────────────────
_PARA_BLOCK_RE = re.compile(
    r"문단\s*"
    r"([A-Z]*\d+(?:\s*[~～\-]\s*[A-Z]*\d+)?)"
    r"((?:\s*[,、]\s*[A-Z]*\d+(?:\s*[~～\-]\s*[A-Z]*\d+)?)*)"
)
_SINGLE_RE = re.compile(r"([A-Z]*\d+)(?:\s*[~～\-]\s*([A-Z]*\d+))?")

# ── 문단 → 섹션 역색인 (lazy) ────────────────────────────────────────────────
_para_to_section: dict[str, dict] | None = None


def _build_para_index() -> dict[str, dict]:
    """TOPIC_CONTENT_MAP에서 문단번호 → {topic, title, desc} 역색인을 구축합니다."""
    global _para_to_section
    if _para_to_section is not None:
        return _para_to_section

    _para_to_section = {}
    for topic_key, topic_data in TOPIC_CONTENT_MAP.items():
        display = topic_data.get("display_name", topic_key)
        for sec in topic_data.get("main_and_bc", {}).get("sections", []):
            info = {"topic": display, "title": sec.get("title", ""), "desc": sec.get("desc", "")}
            for p in sec.get("paras", []):
                for expanded in _expand_para_range(p):
                    _para_to_section[expanded] = info
            for p in sec.get("bc_paras", []):
                for expanded in _expand_para_range(p):
                    _para_to_section[expanded] = info
    return _para_to_section


def _extract_answer_paragraphs(answer: str) -> list[str]:
    """AI 답변에서 인용된 문단 번호를 등장 순서대로 반환합니다 (중복 제거)."""
    seen: set[str] = set()
    ordered: list[str] = []
    for block in _PARA_BLOCK_RE.finditer(answer):
        full_text = block.group(1) + block.group(2)
        for m in _SINGLE_RE.finditer(full_text):
            start, end = m.group(1), m.group(2)
            nums = []
            if end:
                prefix_s = re.match(r"^([A-Z]*)", start).group(1)
                num_s = int(re.search(r"(\d+)$", start).group(1))
                num_e = int(re.search(r"(\d+)$", end).group(1))
                nums = [f"{prefix_s}{n}" for n in range(num_s, num_e + 1)]
            else:
                nums = [start]
            for p in nums:
                if p not in seen:
                    seen.add(p)
                    ordered.append(p)
    return ordered


# ── 메인 렌더 함수 ────────────────────────────────────────────────────────────

def render_pinpoint_topics(topic_keys: list[str]) -> None:
    """AI 답변 기반 근거 패널을 렌더링합니다."""
    _DOC_IDX["counter"] = 4000

    ai_answer = st.session_state.get("ai_answer", "")
    user_query = st.session_state.get("standalone_query", "")

    # 1. 본문 — AI 답변 인용 문단만 표시
    _render_answer_paragraphs(ai_answer)

    # 2. 적용사례/QNA/감리사례 — summary 매칭 (토픽 무관)
    query_vector = embed_query_sync(user_query) if user_query else None
    if query_vector:
        _render_matched_ie(query_vector)
        _render_matched_qna(query_vector)
        _render_matched_findings(query_vector)


# ── 본문 렌더링 ──────────────────────────────────────────────────────────────

def _render_answer_paragraphs(ai_answer: str) -> None:
    """AI 답변에서 인용된 문단을 섹션별로 그룹핑하여 렌더링합니다."""
    para_nums = _extract_answer_paragraphs(ai_answer)
    if not para_nums:
        return

    idx = _build_para_index()

    # DB에서 문단 문서 조회
    chunk_ids = tuple(f"1115-{p}" for p in para_nums)
    raw_docs = fetch_docs_by_para_ids(tuple(para_nums))
    docs_map = {doc.get("chunk_id", ""): doc for doc in raw_docs}

    # 섹션별 그룹핑 (등장 순서 유지)
    groups: dict[str, dict] = {}  # key=section_title → {info, docs}
    ungrouped: list[dict] = []

    for p in para_nums:
        doc = docs_map.get(f"1115-{p}")
        if not doc:
            continue
        sec_info = idx.get(p)
        if sec_info:
            key = f"{sec_info['topic']} > {sec_info['title']}"
            if key not in groups:
                groups[key] = {"info": sec_info, "docs": []}
            groups[key]["docs"].append(doc)
        else:
            ungrouped.append(doc)

    if not groups and not ungrouped:
        return

    st.markdown("### 📖 참조 기준서 조항")

    for group_key, group in groups.items():
        info = group["info"]
        title = info["title"]
        topic = info["topic"]
        desc = info["desc"]

        with st.expander(f"📄 {title}  ({topic})", expanded=True):
            if desc:
                formatted = _format_desc_html(desc)
                st.markdown(
                    f'<div style="line-height:1.75; color:#475569; font-size:0.85em; '
                    f'padding:0.5rem 0.75rem; margin-bottom:0.5rem; background:#f8fafc; '
                    f'border-left:3px solid #60a5fa; border-radius:4px;">'
                    f'{formatted}</div>',
                    unsafe_allow_html=True,
                )
            for doc in group["docs"]:
                _render_doc_inline(doc)

    # 큐레이션에 매핑되지 않은 문단 (BC 등)
    if ungrouped:
        with st.expander(f"📄 기타 참조 문단 ({len(ungrouped)}개)", expanded=False):
            for doc in ungrouped:
                _render_doc_inline(doc)


# ── 적용사례(IE) 렌더링 ──────────────────────────────────────────────────────

def _render_matched_ie(query_vector: list[float]) -> None:
    """서머리 매칭된 IE 적용사례를 렌더링합니다."""
    matched = match_ie_by_summary(query_vector)
    if not matched:
        return

    with st.expander(f"📋 관련 적용사례 ({len(matched)}건)"):
        for case in matched:
            st.markdown(
                f'<div style="display:inline-block; background:#e0e7ff; '
                f'padding:0.15em 0.6em; border-radius:4px; '
                f'font-weight:600; color:#1e3a5f; font-size:0.82em; '
                f'margin:0.3rem 0 0.2rem;">'
                f'{html.escape(case["title"])}  '
                f'<span style="font-weight:400; color:#64748b;">({html.escape(case["topic"])})</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
            if case["desc"]:
                formatted = _format_desc_html(case["desc"])
                st.markdown(
                    f'<div style="line-height:1.75; color:#475569; font-size:0.85em; '
                    f'padding:0.5rem 0.75rem; margin-bottom:0.5rem; background:#f8fafc; '
                    f'border-left:3px solid #60a5fa; border-radius:4px;">'
                    f'{formatted}</div>',
                    unsafe_allow_html=True,
                )
            ie_docs = _fetch_ie_docs_by_range(case["para_range"])
            for doc in ie_docs:
                _render_doc_inline(doc)


# ── QNA 렌더링 ───────────────────────────────────────────────────────────────

def _render_matched_qna(query_vector: list[float]) -> None:
    """서머리 매칭된 QNA를 렌더링합니다."""
    matched_ids = match_qna_by_summary(query_vector)
    if not matched_ids:
        return

    with st.expander(f"💬 관련 질의회신 ({len(matched_ids)}건)"):
        for qid in matched_ids:
            parent = fetch_parent_doc(qid)
            if parent:
                _meta = parent.get("metadata") or {}
                _hier = parent.get("hierarchy") or _meta.get("hierarchy", qid)
                _render_pdr_expander(
                    {**parent, "parent_id": qid, "hierarchy": _hier},
                    doc_index=_next_idx(),
                )


# ── 감리사례 렌더링 ──────────────────────────────────────────────────────────

def _render_matched_findings(query_vector: list[float]) -> None:
    """서머리 매칭된 감리사례를 렌더링합니다."""
    matched = match_findings_by_summary(query_vector)
    if not matched:
        return

    parent = fetch_parent_doc(matched["parent_id"])
    if not parent:
        return

    with st.expander("🚨 관련 감리사례 (1건)"):
        _meta = parent.get("metadata") or {}
        _hier = parent.get("hierarchy") or _meta.get("hierarchy", matched["parent_id"])
        _render_pdr_expander(
            {**parent, "parent_id": matched["parent_id"], "hierarchy": _hier},
            doc_index=_next_idx(),
        )


# ── 공통 헬퍼 ─────────────────────────────────────────────────────────────────

def _fetch_ie_docs_by_range(para_range: str) -> list[dict]:
    """para_range(예: 'IE19~IE24')에 해당하는 IE 문서를 조회합니다."""
    m = re.match(r"^([A-Za-z]*)(\d+)[~～\-]([A-Za-z]*)(\d+)$", para_range)
    if m:
        prefix = m.group(1) or m.group(3)
        start_n, end_n = int(m.group(2)), int(m.group(4))
        para_ids = [f"{prefix}{n}" for n in range(start_n, end_n + 1)]
    else:
        para_ids = [para_range]
    return fetch_docs_by_para_ids(tuple(para_ids))


def _next_idx() -> int:
    idx = _DOC_IDX["counter"]
    _DOC_IDX["counter"] += 1
    return idx


def _render_doc_inline(doc: dict) -> None:
    """단일 문서를 인라인으로 렌더링합니다."""
    title = doc.get("title", "")
    full_text = doc.get("text") or doc.get("full_content") or doc.get("content", "")
    source = doc.get("source", "") or doc.get("category", "")
    hierarchy = doc.get("hierarchy", "")

    if not full_text:
        return

    doc_index = _next_idx()

    if title:
        st.markdown(
            f'<div style="display:inline-block; background:#e0e7ff; '
            f'padding:0.15em 0.6em; border-radius:4px; '
            f'font-weight:600; color:#1e3a5f; font-size:0.82em; '
            f'margin:0.3rem 0 0.2rem;">{html.escape(title)}</div>',
            unsafe_allow_html=True,
        )

    normalized = _normalize_doc_content(full_text, source)
    cleaned = clean_text(normalized)
    st.markdown(cleaned, unsafe_allow_html=True)

    self_ids = _build_self_ids(_get_doc_para_num(doc))
    _render_para_chips(normalized, title or "doc", doc_index, self_ids)

    if hierarchy:
        st.html(
            f'<div class="source-footer">📍 {html.escape(_esc(hierarchy))}</div>'
        )

    st.markdown(
        '<hr style="border:none; border-top:1px solid #e5e7eb; margin:0.25rem 0 0.5rem;">',
        unsafe_allow_html=True,
    )
