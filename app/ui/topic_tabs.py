# app/ui/topic_tabs.py
# 토픽 브라우즈 4탭의 실제 렌더링 로직.
#
# 각 탭은 큐레이션 데이터(topics.json) + MongoDB 원문 조회를 결합합니다.
# DB 조회는 @st.cache_data로 캐싱하여 탭 전환 시 재쿼리를 방지합니다.

import html as _html
import re as _re

import streamlit as st

from app.ui.db import _expand_para_range, fetch_docs_by_para_ids, fetch_parent_doc
from app.ui.doc_helpers import (
    _build_pdr_label,
    _build_self_ids,
    _format_pdr_content,
    _get_doc_para_num,
    _get_parent_field,
    _hierarchy_path,
)
from app.ui.doc_renderers import _render_para_chips
from app.ui.text import _CONTEXT_PREFIX_RE, _esc, clean_text, md_tables_to_html

# 접힌 expander 아래 미리보기 캡션 최대 개수
_MAX_PREVIEW = 3


# ── 공통 헬퍼 ───────────────────────────────────────────────────────────────


def _md_to_html(text: str) -> str:
    """큐레이션 텍스트의 마크다운을 HTML로 변환합니다.

    topics.json의 summary/desc 필드용. HTML div 안에서 렌더되므로 직접 변환합니다.
    """
    # 1) HTML 위험 문자 이스케이프 (XSS 방지)
    t = _html.escape(text)
    # 2) **볼드** → <strong>볼드</strong>
    t = _re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    # 3) 한국어 문장 종결 뒤 줄바꿈 (벽돌 텍스트 방지)
    #    "다.", "음.", "함.", "됨.", "임." 등 모든 한국어 어미 + 마침표 패턴 처리
    #    먼저 "다 ." 같은 공백 정규화, 그 후 줄바꿈 삽입
    t = _re.sub(r"(?<=[가-힣])\s+\.", ".", t)
    t = _re.sub(
        r"(?<=[가-힣])\.\s+",
        ".<br>",
        t,
    )
    # 4) 기존 줄바꿈 처리 (JSON에 \n이 있는 경우)
    t = t.replace("\n\n", "<br>")
    t = t.replace("\n", "<br>")
    return t


@st.cache_data(ttl=300, show_spinner=False)
def _batch_fetch_paras(para_ids: tuple) -> dict[str, dict]:
    """문단 번호 목록을 일괄 조회하고 paraNum 키로 인덱싱합니다."""
    docs = fetch_docs_by_para_ids(para_ids)
    index: dict[str, dict] = {}
    for doc in docs:
        for key in (doc.get("paraNum", ""), doc.get("chunk_id", "")):
            if key:
                index[key] = doc
        cid = doc.get("chunk_id", "")
        if cid and cid.startswith("1115-"):
            index[cid[5:]] = doc
    return index


def _summary_box(text: str) -> None:
    """요약 텍스트를 연한 하늘색 박스로 렌더링합니다."""
    if not text:
        return
    st.markdown(
        f'<div style="line-height:1.75; color:#1e3a5f; font-size:0.9em; '
        f"padding:0.6rem 0.85rem; background:#eef6ff; "
        f"border-left:3px solid #93c5fd; border-radius:4px; "
        f'margin-bottom:0.5rem;">{_md_to_html(text)}</div>',
        unsafe_allow_html=True,
    )


def _desc_blockquote(desc: str) -> None:
    """설명 텍스트를 연한 회색 블록 + 하단 구분선으로 렌더링합니다."""
    if not desc:
        return
    st.markdown(
        f'<div style="line-height:1.75; color:#475569; font-size:0.88em; '
        f"padding:0.5rem 0.75rem; background:#f8fafc; "
        f'border-left:2px solid #cbd5e1; border-radius:2px;">'
        f"{_md_to_html(desc)}</div>"
        f'<hr style="border:none; border-top:1px solid #e2e8f0; margin:0.4rem 0 0.2rem;">',
        unsafe_allow_html=True,
    )


def _strip_context_prefix(text: str, para_num: str = "") -> str:
    """본문 표시 전 불필요한 접두어를 정리합니다.

    1. [문맥: 본문 > ... > 변동대가] 접두어 제거
    2. **[문단 XX]** 또는 [문단 XX] 제거 (badge에서 이미 표시)
       — DB 저장 시 **[문단 10]** 형태(볼드 마크다운)로 저장되므로
         정확한 para_num 기반 문자열 매칭으로 제거
    3. ~ 취소선 방지 (Streamlit markdown이 ~text~를 strikethrough로 파싱)
    """
    import re

    text = _CONTEXT_PREFIX_RE.sub("", text).strip()

    # badge에서 이미 표시하므로 본문의 문단 번호 접두어 제거
    # DB 포맷: **[문단 10]** (볼드 마크다운)
    if para_num:
        for prefix in (
            f"**[문단 {para_num}]**",
            f"**[문단{para_num}]**",
            f"[문단 {para_num}]",
            f"[문단{para_num}]",
        ):
            if text.startswith(prefix):
                text = text[len(prefix) :].strip()
                break

    # ~ 취소선 방지: 숫자/알파벳 사이의 ~ → 전각 ～
    text = re.sub(r"(\d)~(\d)", r"\1～\2", text)
    text = re.sub(r"([A-Z])~([A-Z])", r"\1～\2", text)
    return text


def _render_para_expander(doc: dict, idx: int = 0) -> None:
    """개별 문단 문서를 nested expander로 렌더링합니다 (관련 조항 칩 포함)."""
    title = doc.get("title", "")
    raw_content = doc.get("content") or doc.get("text", "")
    hierarchy = doc.get("hierarchy", "")
    para_num = _get_doc_para_num(doc)

    # [문맥:...] + **[문단 XX]** 접두어 제거 — badge에서 이미 문단 번호 표시
    content = _strip_context_prefix(raw_content, para_num)

    # 제목 결정: title → content 첫 문장 → "문단 XX" 폴백
    # Why: 경과규정(C5, C7A 등) 문서는 title이 비어있어 "문단 C5"로만 표시됨
    if title:
        label = title
    elif content:
        # content는 이미 [문맥:] + **[문단 XX]** 접두어가 제거된 상태
        first_sent = content.split("\n")[0].strip()[:80]
        label = f"[문단 {para_num}] {first_sent}" if first_sent else f"문단 {para_num}"
    else:
        label = f"문단 {para_num}"
    with st.expander(f":material/description: {_esc(label)}", expanded=False):
        if para_num:
            st.markdown(
                f'<span style="display:inline-block; background:#e0e7ff; color:#3730a3; '
                f"font-size:0.8em; font-weight:600; padding:2px 8px; border-radius:4px; "
                f'margin-bottom:0.5rem;">[문단 {_html.escape(para_num)}]</span>',
                unsafe_allow_html=True,
            )
        if content:
            _cleaned = md_tables_to_html(clean_text(content))
            st.markdown(_cleaned, unsafe_allow_html=True)

        # 관련 조항 칩 — 자기 자신 제외, 클릭 시 모달 팝업
        if content:
            self_ids = _build_self_ids(para_num)
            _render_para_chips(content, label, idx, self_ids)

        # 간격 축소: st.divider() 대신 얇은 선
        st.markdown(
            "<hr style='border:none; border-top:1px solid #e2e8f0; margin:0.3rem 0;'>",
            unsafe_allow_html=True,
        )
        if hierarchy:
            st.html(
                f'<div class="source-footer">📍 출처 경로: {_html.escape(hierarchy)}</div>'
            )


def _render_preview_captions(para_ids: list[str], para_index: dict[str, dict]) -> None:
    """접힌 expander 아래에 최대 3개 미리보기 캡션 + "..."을 표시합니다."""
    titles: list[str] = []
    for p in para_ids:
        doc = para_index.get(p)
        if doc:
            title = doc.get("title") or ""
            if not title:
                # title 없는 문단(경과규정 등): content 첫 줄에서 추출
                raw = (doc.get("content") or doc.get("text", ""))
                raw = _strip_context_prefix(raw, _get_doc_para_num(doc))
                first_sent = raw.split("\n")[0].strip()[:80] if raw else ""
                title = f"[문단 {p}] {first_sent}" if first_sent else f"문단 {p}"
            titles.append(title)
    if not titles:
        return
    lines = titles[:_MAX_PREVIEW]
    html_parts = "".join(
        f'<div style="font-size:0.82em; color:#9ca3af; '
        f'line-height:1.4; margin:0 0 3px 0.25rem;">└ {_html.escape(t)}</div>'
        for t in lines
    )
    if len(titles) > _MAX_PREVIEW:
        html_parts += (
            '<div style="font-size:0.82em; color:#9ca3af; '
            'line-height:1.4; margin:0 0 3px 0.25rem;">...</div>'
        )
    # expander 아래 적절한 간격 유지
    st.html(
        f'<div style="margin-top:-0.25rem; margin-bottom:0.15rem;">{html_parts}</div>'
    )


def _collect_expanded_ids(sections: list[dict]) -> list[str]:
    """sections에서 모든 문단 ID를 수집하고 범위를 확장합니다."""
    raw_ids: list[str] = []
    for sec in sections:
        raw_ids.extend(sec.get("paras", []))
        raw_ids.extend(sec.get("bc_paras", []))
    expanded: list[str] = []
    for pid in raw_ids:
        expanded.extend(_expand_para_range(pid))
    return expanded


# ── 탭 1: 본문·BC ──────────────────────────────────────────────────────────


def _render_main_bc_tab(data: dict, topic_name: str = "") -> None:
    """본문 및 결론도출근거(BC) 탭을 렌더링합니다."""
    summary = data.get("summary", "")
    sections = data.get("sections", [])

    if not sections:
        fallback = (
            f"기준서 본문 및 결론도출근거(BC) 중 '{topic_name}' 원칙을 직접 다루는 문단이 현재 등록되어 있지 않습니다."
            if topic_name
            else "등록된 본문/BC 데이터가 없습니다."
        )
        st.caption(fallback)
        return

    _summary_box(summary)
    all_ids = _collect_expanded_ids(sections)
    para_index = _batch_fetch_paras(tuple(all_ids)) if all_ids else {}

    for i, sec in enumerate(sections):
        title = sec.get("title", f"섹션 {i + 1}")
        desc = sec.get("desc", "")
        paras = sec.get("paras", [])
        bc_paras = sec.get("bc_paras", [])

        # BC-only 섹션: 제목에 BC 범위 표시 (접힌 상태에서도 보이도록)
        if bc_paras and not paras:
            all_bc = [ep for _p in bc_paras for ep in _expand_para_range(_p)]
            if len(all_bc) >= 2:
                title += f" ({all_bc[0]}～{all_bc[-1]})"
            elif all_bc:
                title += f" ({all_bc[0]})"

        with st.expander(f":material/article: {_esc(title)}", expanded=(i == 0)):
            _desc_blockquote(desc)

            if paras:
                st.markdown("**기준서 원문**")
                with st.container(gap="xsmall"):
                    for p in paras:
                        for ep in _expand_para_range(p):
                            doc = para_index.get(ep)
                            if doc:
                                _render_para_expander(doc, idx=i)

            if bc_paras:
                if paras:
                    st.markdown(
                        "<hr style='border:none; border-top:1px solid #e2e8f0; margin:0.3rem 0;'>",
                        unsafe_allow_html=True,
                    )
                # BC 범위 표시: ["BC159", "BC160"] → "결론도출근거(BC159～BC160)"
                all_bc = []
                for _p in bc_paras:
                    all_bc.extend(_expand_para_range(_p))
                if len(all_bc) >= 2:
                    bc_range = f"({all_bc[0]}～{all_bc[-1]})"
                elif all_bc:
                    bc_range = f"({all_bc[0]})"
                else:
                    bc_range = "(BC)"
                st.markdown(f"**결론도출근거{bc_range}**")
                with st.container(gap="xsmall"):
                    for p in bc_paras:
                        for ep in _expand_para_range(p):
                            doc = para_index.get(ep)
                            if doc:
                                _render_para_expander(doc, idx=i)

        # 미리보기 캡션 (최대 3개 + "...")
        all_p: list[str] = []
        for p in paras + bc_paras:
            all_p.extend(_expand_para_range(p))
        _render_preview_captions(all_p, para_index)


# ── 탭 2: 적용사례(IE) ─────────────────────────────────────────────────────


def _render_ie_tab(data: dict, topic_name: str = "") -> None:
    """적용사례(IE) 탭을 렌더링합니다."""
    summary = data.get("summary", "")
    cases = data.get("cases", [])

    if not cases:
        # cases가 없으면 항상 fallback 메시지 표시
        # Why: summary에 QNA 등 다른 탭 내용이 잘못 들어간 경우가 있어
        #       summary를 대체 표시하면 혼란을 줌
        fallback = (
            f"기준서 부록의 적용사례(IE) 중 '{topic_name}' 원칙만을 단독으로 설명하기 위해 마련된 별도의 사례는 없습니다."
            if topic_name
            else "등록된 적용사례가 없습니다."
        )
        st.caption(fallback)
        return

    all_ie_ids: list[str] = []
    for case in cases:
        pr = case.get("para_range", "")
        if pr:
            all_ie_ids.extend(_expand_para_range(pr))
    ie_index = _batch_fetch_paras(tuple(all_ie_ids)) if all_ie_ids else {}

    for i, case in enumerate(cases):
        case_title = case.get("title", f"사례 {i + 1}")
        case_desc = case.get("desc", "")
        para_range = case.get("para_range", "")

        with st.expander(f":material/article: {_esc(case_title)}", expanded=(i == 0)):
            _desc_blockquote(case_desc)

            if para_range:
                with st.container(gap="xsmall"):
                    para_ids = _expand_para_range(para_range)
                    for pid in para_ids:
                        doc = ie_index.get(pid)
                        if doc:
                            _render_para_expander(doc, idx=100 + i)


# ── 탭 3: 질의회신(QNA) ────────────────────────────────────────────────────


def _render_qna_tab(data: dict, topic_name: str = "") -> None:
    """질의회신(QNA) 탭을 렌더링합니다."""
    summary = data.get("summary", "")
    qna_ids = data.get("qna_ids", [])
    qna_descs: dict = data.get("qna_descs", {})

    if not qna_ids:
        fallback = (
            f"회계기준원·금융감독원 질의회신 중 '{topic_name}' 원칙만을 단독으로 다루는 회신은 현재 등록되어 있지 않습니다."
            if topic_name
            else "등록된 질의회신이 없습니다."
        )
        st.caption(fallback)
        return

    for i, qna_id in enumerate(qna_ids):
        parent = fetch_parent_doc(qna_id)
        desc = qna_descs.get(qna_id, "")

        if parent:
            raw_title = _get_parent_field(parent, "title", qna_id)
            hierarchy = _get_parent_field(parent, "hierarchy")
            content = parent.get("content", "")
            label = _build_pdr_label(qna_id, raw_title, content)

            with st.expander(f":material/description: {_esc(label)}", expanded=False):
                hier_path = _hierarchy_path(hierarchy) if hierarchy else ""
                if hier_path:
                    st.markdown(
                        f'<div style="font-size:0.78em; color:#6b7280; background:#f1f5f9; '
                        f"display:inline-block; padding:2px 10px; border-radius:12px; "
                        f'margin-bottom:0.5rem;">🏷️ {_html.escape(hier_path)}</div>',
                        unsafe_allow_html=True,
                    )
                _desc_blockquote(desc)

                if content:
                    adjusted = _format_pdr_content(content)
                    _cleaned = md_tables_to_html(clean_text(adjusted))
                    st.markdown(_cleaned, unsafe_allow_html=True)
                    # 본문 내 참조 문단을 클릭 가능한 칩으로 표시
                    _render_para_chips(content, qna_id, doc_index=200 + i)

                st.html(
                    f'<div class="source-footer">📍 출처 경로: '
                    f"{_html.escape(hierarchy)}</div>"
                )
        else:
            with st.expander(f":material/description: {qna_id}", expanded=False):
                _desc_blockquote(desc)
                st.warning(f"'{qna_id}' 문서를 DB에서 찾을 수 없습니다.")


# ── 탭 4: 감리지적사례 ─────────────────────────────────────────────────────


def _render_findings_tab(data: dict, topic_name: str = "") -> None:
    """감리지적사례 탭을 렌더링합니다."""
    summary = data.get("summary", "")
    finding_ids = data.get("finding_ids", [])
    finding_descs: dict = data.get("finding_descs", {})

    if not finding_ids:
        fallback = (
            f"금융감독원 감리지적사례 중 '{topic_name}' 원칙만을 단독으로 다루는 사례는 현재 등록되어 있지 않습니다."
            if topic_name
            else "등록된 감리지적사례가 없습니다."
        )
        st.caption(fallback)
        return

    for i, fid in enumerate(finding_ids):
        parent = fetch_parent_doc(fid)
        desc = finding_descs.get(fid, "")

        if parent:
            raw_title = _get_parent_field(parent, "title", fid)
            hierarchy = _get_parent_field(parent, "hierarchy")
            content = parent.get("content", "")
            label = _build_pdr_label(fid, raw_title, content)

            with st.expander(f":material/description: {_esc(label)}", expanded=False):
                hier_path = _hierarchy_path(hierarchy) if hierarchy else ""
                if hier_path:
                    st.markdown(
                        f'<div style="font-size:0.78em; color:#6b7280; background:#f1f5f9; '
                        f"display:inline-block; padding:2px 10px; border-radius:12px; "
                        f'margin-bottom:0.5rem;">🏷️ {_html.escape(hier_path)}</div>',
                        unsafe_allow_html=True,
                    )
                _desc_blockquote(desc)

                if content:
                    adjusted = _format_pdr_content(content)
                    _cleaned = md_tables_to_html(clean_text(adjusted))
                    st.markdown(_cleaned, unsafe_allow_html=True)
                    # 본문 내 참조 문단을 클릭 가능한 칩으로 표시
                    _render_para_chips(content, fid, doc_index=300 + i)

                st.html(
                    f'<div class="source-footer">📍 출처 경로: '
                    f"{_html.escape(hierarchy)}</div>"
                )
        else:
            with st.expander(f":material/description: {fid}", expanded=False):
                _desc_blockquote(desc)
                st.warning(f"'{fid}' 문서를 DB에서 찾을 수 없습니다.")
