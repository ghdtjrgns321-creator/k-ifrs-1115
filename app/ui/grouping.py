# app/ui/grouping.py
# 본문/적용지침B/결론도출근거 문서를 소제목 > 소소제목 2단계로 그룹핑.
#
# 디자인:
#   변동대가                          ← 소제목 (볼드 텍스트)
#     ▸ 변동대가 추정치를 제약함 (3건)  ← 소소제목 (접을 수 있는 expander)
#       📄 문단 56 - 제목              ← 문서 카드 (flat)
#   📂 다른 주제 더보기                ← 나머지

import re

import streamlit as st

from app.ui.components import _get_doc_para_num, _render_document_expander
from app.ui.text import _esc


def _para_sort_key(doc: dict) -> tuple[str, int, str]:
    """B59 → ("B", 59, ""), B59A → ("B", 59, "A")."""
    para = _get_doc_para_num(doc)
    m = re.match(r"([A-Za-z]*)(\d+)([A-Za-z]*)", para)
    if m:
        return (m.group(1), int(m.group(2)), m.group(3))
    return ("ZZ", 999999, "")


def _extract_topic_key(doc: dict) -> tuple[str, str]:
    """hierarchy에서 (소제목, 소소제목) 추출."""
    hierarchy = doc.get("hierarchy", "")
    source = doc.get("source") or doc.get("category", "")
    parts = [p.strip() for p in hierarchy.split(" > ") if p.strip()]

    if "결론도출근거" in source:
        if len(parts) >= 4:
            return (parts[3], parts[4] if len(parts) >= 5 else "")
        elif len(parts) >= 3:
            return (parts[2], "")
        return ("", "")

    if source == "적용지침B":
        if len(parts) < 2:
            return ("", "")
        return (parts[1], parts[2] if len(parts) >= 3 else "")

    if len(parts) < 3:
        return ("", parts[1] if len(parts) >= 2 else "")
    return (parts[2], parts[3] if len(parts) >= 4 else "")


def _get_parent_category(doc: dict) -> str:
    """hierarchy에서 대분류 추출."""
    hierarchy = doc.get("hierarchy", "")
    source = doc.get("source") or doc.get("category", "")
    parts = [p.strip() for p in hierarchy.split(" > ") if p.strip()]
    if source == "본문" and len(parts) >= 2:
        return parts[1]
    if "결론도출근거" in source and len(parts) >= 3:
        return parts[2]
    return ""


def _clean_title(title: str) -> str:
    """소제목에서 "(문단 XX~YY)" 부분을 제거합니다."""
    return re.sub(r"\s*[\(（]문단\s*[A-Za-z0-9~～\-]+[\)）]\s*", "", title).strip()


# ── 렌더링 ────────────────────────────────────────────────────────────────────


def _render_sub_grouped(
    items: list[tuple[str, int, dict]],
    allowed_sources: tuple[str, ...] = ("본문", "적용지침B"),
) -> None:
    """소소제목별 expander + retrieved 문서만 렌더링."""
    sub_groups: dict[str, list[tuple[int, dict]]] = {}
    sub_ungrouped: list[tuple[int, dict]] = []

    for minor, idx, doc in items:
        if minor:
            sub_groups.setdefault(minor, []).append((idx, doc))
        else:
            sub_ungrouped.append((idx, doc))

    # 소소제목이 없으면 flat 표시
    if not sub_groups:
        for idx, doc in sub_ungrouped:
            _render_document_expander(doc, doc_index=idx)
        return

    for idx, doc in sub_ungrouped:
        _render_document_expander(doc, doc_index=idx)

    # 소소제목 → expander (2번째 계층, 마지막)
    for minor_title, minor_items in sorted(
        sub_groups.items(),
        key=lambda kv: _para_sort_key(kv[1][0][1]),
    ):
        title = _clean_title(minor_title)
        with st.expander(f"{_esc(title)} ({len(minor_items)}건)", expanded=False):
            for idx, doc in minor_items:
                _render_document_expander(doc, doc_index=idx)


def _render_major_section(
    major_title: str,
    items: list[tuple[str, int, dict]],
    allowed_sources: tuple[str, ...] = ("본문", "적용지침B"),
) -> None:
    """소제목 헤더 + 소소제목 렌더링."""
    title = _clean_title(major_title)
    st.markdown(f"**{_esc(title)}**")
    _render_sub_grouped(items, allowed_sources=allowed_sources)


# ── 진입점 ────────────────────────────────────────────────────────────────────


def _render_topic_grouped_docs(
    docs: list[dict],
    idx_offset: int = 0,
    score_ordered: list[dict] | None = None,
    search_query: str = "",
    allowed_sources: tuple[str, ...] = ("본문", "적용지침B"),
) -> None:
    """소제목 > 소소제목 2단계 그룹핑 렌더링."""
    grouped: dict[str, list[tuple[str, int, dict]]] = {}
    ungrouped: list[tuple[int, dict]] = []

    for i, doc in enumerate(docs):
        major, minor = _extract_topic_key(doc)
        if major:
            grouped.setdefault(major, []).append((minor, idx_offset + i, doc))
        else:
            ungrouped.append((idx_offset + i, doc))

    if not grouped:
        for idx, doc in ungrouped:
            _render_document_expander(doc, doc_index=idx)
        return

    # score 1위 소제목 → 메인
    group_score_sum: dict[str, float] = {}
    if score_ordered:
        for doc in score_ordered:
            candidate, _ = _extract_topic_key(doc)
            if candidate and candidate in grouped:
                group_score_sum[candidate] = (
                    group_score_sum.get(candidate, 0.0) + doc.get("score", 0.0)
                )
        if search_query and group_score_sum:
            kws = [
                w for w in re.sub(r"[^\w]", " ", search_query).split() if len(w) >= 2
            ]
            for gname in group_score_sum:
                match_cnt = sum(1 for kw in kws if kw in gname)
                if match_cnt:
                    group_score_sum[gname] += match_cnt * 100.0

    top_major = (
        max(group_score_sum, key=lambda k: group_score_sum[k])
        if group_score_sum
        else max(grouped.keys(), key=lambda k: len(grouped[k]))
    )
    top_items = grouped.pop(top_major)
    top_score = group_score_sum.get(top_major, 1.0) or 1.0

    # 같은 대분류 관련 소제목 통합
    top_category = ""
    for _, _, doc in top_items:
        top_category = _get_parent_category(doc)
        if top_category:
            break

    if top_category:
        for m, s in list(group_score_sum.items()):
            if m not in grouped or s < top_score * 0.30:
                continue
            m_cat = ""
            for _, _, doc in grouped[m]:
                m_cat = _get_parent_category(doc)
                if m_cat:
                    break
            if m_cat == top_category:
                for minor, idx, doc in grouped.pop(m):
                    top_items.append((minor if minor else m, idx, doc))

    # 메인 렌더링
    _render_major_section(top_major, top_items, allowed_sources=allowed_sources)

    # 나머지 → 더보기
    other_count = len(grouped) + (1 if ungrouped else 0)
    if other_count == 0:
        return

    st.divider()
    with st.expander(f"다른 주제 더보기 ({other_count}건)", expanded=False):
        for major_title, items in sorted(
            grouped.items(),
            key=lambda kv: _para_sort_key(kv[1][0][2]),
        ):
            title = _clean_title(major_title)
            st.markdown(f"**{_esc(title)}**")
            _render_sub_grouped(items, allowed_sources=allowed_sources)

        if ungrouped:
            st.markdown("**기타**")
            for idx, doc in ungrouped:
                _render_document_expander(doc, doc_index=idx)
