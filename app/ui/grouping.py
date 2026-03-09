# app/ui/grouping.py
# 본문/적용지침B/결론도출근거 문서를 소제목 > 소소제목 2단계로 그룹핑.
#
# 핵심 로직:
#   1. 소제목별 그룹화 (hierarchy parts 기반)
#   2. score 1위 소제목 → 메인
#   3. 같은 대분류(예: "인식") + score threshold인 소제목 → 메인에 소소제목 배지로 통합
#   4. 나머지 → 더보기
#
# 예: "계약 식별" 검색 시
#   [메인] 계약을 식별함                    ← score 1위 소제목
#     📄 문단 9~13 (retrieved, flat)
#     ▸ 계약의 결합 (3건)                  ← 같은 대분류 + threshold → 소소제목 배지
#       📄 문단 17, B3, B4
#     ▸ 계약변경 (4건)
#       📄 문단 18~21
#   📂 다른 주제 더보기
#     ▸ 수행의무를 식별함 (3건)
#       ▸ 고객과의 계약으로 한 약속 (2건)  ← 4단계 hierarchy의 자연 소소제목

import re

import streamlit as st

from app.ui.components import _get_doc_para_num, _render_document_expander
from app.ui.db import fetch_docs_by_topic
from app.ui.text import _esc


# ━━━ 유틸리티 함수 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _para_sort_key(doc: dict) -> tuple[str, int, str]:
    """B59 → ("B", 59, ""), B59A → ("B", 59, "A") — suffix 포함 자연 정렬."""
    para = _get_doc_para_num(doc)
    m = re.match(r"([A-Za-z]*)(\d+)([A-Za-z]*)", para)
    if m:
        return (m.group(1), int(m.group(2)), m.group(3))
    return ("ZZ", 999999, "")


def _extract_topic_key(doc: dict) -> tuple[str, str]:
    """hierarchy에서 (소제목, 소소제목) 추출.

    source별 hierarchy 구조가 다르므로 분기 처리:
      본문:        본문 > 대분류 > 소제목 > 소소제목         → (parts[2], parts[3])
      적용지침B:   부록 B 적용지침 > 소제목 > 소소제목       → (parts[1], parts[2])
      결론도출근거: 결론도출근거 > IFRS 15... > 대 > 소 > 소소 → (parts[3], parts[4])
    """
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
        # 부록 B 적용지침 > 소제목 > 소소제목
        if len(parts) < 2:
            return ("", "")
        return (parts[1], parts[2] if len(parts) >= 3 else "")

    # 본문 (및 기타): 본문 > 대분류 > 소제목 > 소소제목
    if len(parts) < 3:
        return ("", parts[1] if len(parts) >= 2 else "")
    return (parts[2], parts[3] if len(parts) >= 4 else "")


def _get_parent_category(doc: dict) -> str:
    """hierarchy에서 대분류 추출 — 같은 대분류의 소제목들을 메인에 통합할지 결정.

    본문: parts[1] (인식, 측정, 표시 등)
    결론도출근거: parts[2] (적용범위 등)
    적용지침B: 대분류 없음 → ""
    """
    hierarchy = doc.get("hierarchy", "")
    source = doc.get("source") or doc.get("category", "")
    parts = [p.strip() for p in hierarchy.split(" > ") if p.strip()]
    if source == "본문" and len(parts) >= 2:
        return parts[1]
    if "결론도출근거" in source and len(parts) >= 3:
        return parts[2]
    return ""


def _fetch_minor_docs(
    minor_title: str,
    fallback_docs: list[dict],
    allowed_sources: tuple[str, ...],
) -> list[dict]:
    """소소제목 이름으로 DB에서 allowed_sources 전체 문단 조회.

    DB 결과 없으면 fallback_docs(retrieved 문서) 반환.
    """
    result = sorted(
        fetch_docs_by_topic(minor_title, allowed_sources), key=_para_sort_key
    )
    return result if result else fallback_docs


# ━━━ 렌더링 함수 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _render_sub_grouped(
    items: list[tuple[str, int, dict]],
    allowed_sources: tuple[str, ...] = ("본문", "적용지침B"),
) -> None:
    """items를 소소제목별 배지 + 문단 렌더링.

    items 형식: [(minor, idx, doc), ...]
    minor가 있으면 → 소소제목 배지 + DB 전체 조회 (allowed_sources)
    minor가 없으면 → flat 표시
    """
    sub_groups: dict[str, list[tuple[int, dict]]] = {}
    sub_ungrouped: list[tuple[int, dict]] = []

    for minor, idx, doc in items:
        if minor:
            sub_groups.setdefault(minor, []).append((idx, doc))
        else:
            sub_ungrouped.append((idx, doc))

    if not sub_groups:
        for idx, doc in sub_ungrouped:
            _render_document_expander(doc, doc_index=idx)
        return

    # 소소제목 없는 retrieved 문단 먼저 flat 표시
    for idx, doc in sub_ungrouped:
        _render_document_expander(doc, doc_index=idx)

    # 소소제목별 배지 + DB 전체 조회
    counter = 5000  # idx 충돌 방지용 오프셋
    for minor_title, minor_items in sorted(
        sub_groups.items(),
        key=lambda kv: _para_sort_key(kv[1][0][1]),
    ):
        fallback = [doc for _, doc in minor_items]
        all_minor_docs = _fetch_minor_docs(minor_title, fallback, allowed_sources)

        # 연한 보라색 소소제목 배지
        st.markdown(
            f'<div style="margin:0.75rem 0 0.3rem; padding:0.3rem 0.65rem; '
            f"background:linear-gradient(135deg, #eef2ff 0%, #e0e7ff 100%); "
            f"border-left:3px solid #818cf8; border-radius:5px; "
            f'font-size:0.83em; color:#4338ca; font-weight:600;">'
            f"▸ {_esc(minor_title)} "
            f'<span style="font-size:0.78em; color:#6366f1; font-weight:400;">'
            f"({len(all_minor_docs)}건)</span></div>",
            unsafe_allow_html=True,
        )
        for doc in all_minor_docs:
            _render_document_expander(doc, doc_index=counter)
            counter += 1


def _render_major_section(
    major_title: str,
    items: list[tuple[str, int, dict]],
    allowed_sources: tuple[str, ...] = ("본문", "적용지침B"),
) -> None:
    """보라색 소제목 헤더 + 소소제목 그룹핑 렌더링."""
    st.markdown(
        f'<div style="margin-top:0.9rem; padding:0.35rem 0.75rem; '
        f"background:linear-gradient(135deg, #f5f0ff 0%, #ede5ff 100%); "
        f"border-left:4px solid #7c3aed; "
        f'border-radius:6px; font-size:0.92em; color:#4c1d95; font-weight:700;">'
        f"{_esc(major_title)}</div>",
        unsafe_allow_html=True,
    )
    _render_sub_grouped(items, allowed_sources=allowed_sources)


# ━━━ 진입점 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _render_topic_grouped_docs(
    docs: list[dict],
    idx_offset: int = 0,
    score_ordered: list[dict] | None = None,
    search_query: str = "",
    allowed_sources: tuple[str, ...] = ("본문", "적용지침B"),
) -> None:
    """소제목 > 소소제목 2단계 그룹핑 렌더링.

    1. 소제목별 그룹화
    2. score 1위 소제목 → 메인
    3. 같은 대분류 + score >= top * 30% → 메인에 소소제목 배지로 통합
    4. 나머지 → 더보기 (소제목 expander > 소소제목 배지)
    """
    # ── 1. 소제목별 그룹화 ────────────────────────────────────────────────
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

    # ── 2. 메인 소제목 선택: score 합계 + 검색 키워드 보너스 ─────────────
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

    # ── 3. 관련 소제목 통합: 같은 대분류 + score threshold ────────────────
    # top_major의 대분류 확인 (예: "인식")
    top_category = ""
    for _, _, doc in top_items:
        top_category = _get_parent_category(doc)
        if top_category:
            break

    RELATED_THRESHOLD = 0.30
    related_majors: list[str] = []
    if top_category:
        for m, s in group_score_sum.items():
            if m not in grouped:
                continue
            if s < top_score * RELATED_THRESHOLD:
                continue
            # 같은 대분류인지 확인
            m_category = ""
            for _, _, doc in grouped[m]:
                m_category = _get_parent_category(doc)
                if m_category:
                    break
            if m_category == top_category:
                related_majors.append(m)

    # 관련 소제목을 top_items에 merge — 소제목 이름을 minor(소소제목)로 재분류
    for m in sorted(
        related_majors, key=lambda x: group_score_sum.get(x, 0.0), reverse=True
    ):
        for minor, idx, doc in grouped.pop(m):
            # 기존 minor가 있으면 유지 (4단계 hierarchy), 없으면 소제목명을 minor로
            effective_minor = minor if minor else m
            top_items.append((effective_minor, idx, doc))

    # ── 4. 메인 렌더링 ──────────────────────────────────────────────────
    _render_major_section(top_major, top_items, allowed_sources=allowed_sources)

    # ── 5. 나머지 → 더보기 ──────────────────────────────────────────────
    other_count = len(grouped) + (1 if ungrouped else 0)
    if other_count == 0:
        return

    st.markdown(
        "<div style='border-top:1.5px dashed #d8cef0; margin:1.25rem 0 0.25rem;'></div>",
        unsafe_allow_html=True,
    )

    with st.expander("📂 다른 주제 더보기", expanded=False):
        for major_title, items in sorted(
            grouped.items(),
            key=lambda kv: _para_sort_key(kv[1][0][2]),
        ):
            with st.expander(
                f"▸ {_esc(major_title)} ({len(items)}건)", expanded=False
            ):
                _render_sub_grouped(items, allowed_sources=allowed_sources)

        if ungrouped:
            with st.expander(f"▸ 기타 ({len(ungrouped)}건)", expanded=False):
                for idx, doc in ungrouped:
                    _render_document_expander(doc, doc_index=idx)
