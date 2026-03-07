# app/ui/components.py
# 재사용 가능한 UI 컴포넌트 함수들.
#
# - _get_doc_para_num: 문서에서 paraNum을 안정적으로 추출
# - _build_self_ids:   자기참조 제외용 ID 집합 생성
# - _render_para_chips: 문단 참조 필 태그 렌더링 (evidence/modal 양쪽에서 사용)
# - _render_document_expander: 카드형 아코디언 문서 렌더링
# - _render_evidence_panel:    카테고리별 아코디언 패널 렌더링

import html
import re

import streamlit as st

from app.ui.constants import ACCORDION_GROUPS
from app.ui.db import _validate_refs_against_db
from app.ui.text import (
    _CONTEXT_PREFIX_RE,
    _PARA_REF_RE,
    _esc,
    _normalize_doc_content,
    clean_text,
)


def _get_doc_para_num(doc: dict) -> str:
    """다양한 경로에서 문단 번호(paraNum)를 신뢰성 있게 추출합니다.

    LangChain MongoDBAtlasVectorSearch는 paraNum을 metadata 서브도큐먼트 안에 저장합니다.
    따라서 doc.get('paraNum')은 항상 None이 되어 자기참조 필터링이 작동하지 않습니다.
    시도 순서:
      1. doc['metadata']['paraNum'] — LangChain 실제 저장 위치
      2. doc['paraNum']             — 직접 저장된 경우
      3. 본문 첫 토큰 regex   — 최후 수단
    """
    # 1) metadata 서브도큐먼트 (LangChain 기본 저장 방식)
    meta = doc.get("metadata") or {}
    para = meta.get("paraNum", "") or ""
    if para.strip():
        return para.strip()
    # 2) 루트 레벨
    para = doc.get("paraNum", "") or ""
    if para.strip():
        return para.strip()
    # 3) 본문 첫 토큰에서 추출 (예: 'B62 라이선스가...' → 'B62')
    # [문맥: ...] 접두어 제거 필수 — 제거 없이는 regex가 '[' 를 보고 실패하여
    # paraNum 추출이 안 되고 self_ids가 비어 자기참조 필터링이 작동하지 않음
    text = (
        doc.get("text") or doc.get("page_content") or doc.get("content", "")
    ).strip()
    text = _CONTEXT_PREFIX_RE.sub("", text).strip()
    m = re.match(r"^([A-Z]{0,2}\d+[A-Za-z]?)(?=\s|$)", text)
    return m.group(1) if m else ""


def _build_self_ids(para_id: str) -> set[str]:
    """paraNum 문자열로부터 자기참조 제외용 ID 집합을 생성합니다.

    '문단 B52', '문단B52', 'B52', '52' 등 모든 표기 형식을 포함하여
    어떤 표기로 나와도 자기참조가 필터링되도록 합니다.
    """
    ids: set[str] = set()
    if not para_id:
        return ids
    # chunk_id는 '본문___문단52' 같은 형식일 수 있으므로 마지막 '__' 뒤 추출
    bare = para_id.split("__")[-1].strip() if "__" in para_id else para_id.strip()
    ids.add(bare)
    ids.add(f"문단 {bare}")
    ids.add(f"문단{bare}")
    # 숫자만인 경우 접두사 없는 숫자도 추가
    numeric = re.sub(r"^[A-Za-z]+", "", bare)
    if numeric:
        ids.add(numeric)
    return ids


def _render_para_chips(
    text: str, context_key: str, doc_index: int = 0, self_ids: set[str] | None = None
) -> None:
    """본문에서 탐지된 문단 참조를 inline 필 태그로 렌더링합니다.

    text: HTML 전 정규화된 텍스트 (raw normalized text, NOT cleaned HTML)
    self_ids: 자기 참조 제외할 ID 집합 (예: {'B52', '문단 B52', '52'})
    클릭 시 show_modal=True + modal_history 설정으로 모달을 트리거합니다.
    """
    self_ids = self_ids or set()
    all_refs = list(dict.fromkeys(_PARA_REF_RE.findall(text)))
    refs = [r for r in all_refs if r not in self_ids]  # 자기참조 제외
    if not refs:
        return

    # DB 검증: 실제 존재하는 문단만 표시
    # 정규식 오탐(서식코드, 가짜 번호 등)을 DB hit 여부로 최종 필터링
    refs = list(_validate_refs_against_db(tuple(refs)))
    if not refs:
        return

    MAX_CHIPS = 8
    display_refs = refs[:MAX_CHIPS]

    st.caption("🔗 관련 조항")
    # doc_index를 포함시켜 같은 제목 문서끼리도 키 충돌 방지
    safe_key = re.sub(r"[^\w]", "_", f"chips_{doc_index}_{context_key}")

    def outer_pill_callback():
        val = st.session_state[safe_key]
        if val:
            st.session_state.modal_history = [val]
            st.session_state.show_modal = True
            st.session_state[safe_key] = None  # 시각적 선택 상태 초기화

    st.pills(
        label="관련 조항",
        options=display_refs,
        label_visibility="collapsed",
        key=safe_key,
        on_change=outer_pill_callback,
    )
    if len(refs) > MAX_CHIPS:
        st.caption(f"외 {len(refs) - MAX_CHIPS}개 조항 참조")


def _render_document_expander(doc: dict, doc_index: int = 0) -> None:
    """개별 문서를 카드 레이아웃의 Expander로 렌더링합니다.

    내부 포맷(템플릿):
      1. 정제된 본문 — clean_text 파이프라인 통과 후 st.markdown
      2. 관련 조항 칩 — st.pills로 렌더링(클릭 시 st.dialog 모달 호출)
      3. 출처 경로 회색 박스 (커스텀 HTML div)
    """
    hierarchy = doc.get("hierarchy", "출처 없음")
    title = doc.get("title", "")
    source = doc.get("source", "")

    # 전문 추출: "text" → "full_content" → "content" 순서로 폴백
    full_text = doc.get("text") or doc.get("full_content") or doc.get("content", "")

    # Expander 라벨: title이 있으면 사용, 없으면 hierarchy 폴백
    expander_label = title if title else hierarchy

    with st.expander(f"📄 {_esc(expander_label)}", expanded=False):
        # 1️⃣ 본문 정규화 + 클리닝
        normalized = _normalize_doc_content(full_text, source)
        cleaned = clean_text(normalized)

        # 2️⃣ 본문 렌더링 — clean_text가 HTML 태그를 포함하므로 unsafe_allow_html=True
        st.markdown(cleaned, unsafe_allow_html=True)

        # 3️⃣ 관련 조항 칩: raw text 기반으로 탐지, 자기 참조 제외
        self_ids = _build_self_ids(_get_doc_para_num(doc))
        _render_para_chips(normalized, expander_label, doc_index, self_ids)

        # 4️⃣ 구분선
        st.divider()

        # 5️⃣ 출처 경로 — 회색 박스
        st.html(
            f'<div class="source-footer">📍 출처 경로: {html.escape(_esc(hierarchy))}</div>'
        )


def _render_docs_with_ie_grouping(docs: list[dict], idx_offset: int = 0) -> None:
    """문서 목록을 렌더링합니다. IE 적용사례는 case_group_title로 서브 그룹화합니다.

    IE 문서 중 case_group_title이 동일한 것들은 "사례 N: 제목" 헤더 아래 묶어서 표시합니다.
    case_group_title 없는 IE(챕터 소개글 등)와 다른 카테고리는 개별 카드로 표시합니다.
    """
    # IE 문서만 그룹화 대상 — 다른 카테고리는 기존 방식 그대로
    ie_groups: dict[str, list[tuple[int, dict]]] = {}  # case_group_title → [(원래idx, doc)]
    non_ie_docs: list[tuple[int, dict]] = []

    for i, doc in enumerate(docs):
        if doc.get("source") == "적용사례IE":
            cgt = doc.get("case_group_title", "")
            if cgt:
                ie_groups.setdefault(cgt, []).append((idx_offset + i, doc))
            else:
                non_ie_docs.append((idx_offset + i, doc))
        else:
            non_ie_docs.append((idx_offset + i, doc))

    # 비-IE 문서 먼저 렌더링
    for idx, doc in non_ie_docs:
        _render_document_expander(doc, doc_index=idx)

    # IE 그룹별 렌더링
    for case_group_title, group_items in ie_groups.items():
        # 그룹이 1개 문서만 있으면 그룹 헤더 없이 바로 렌더링
        if len(group_items) == 1:
            idx, doc = group_items[0]
            _render_document_expander(doc, doc_index=idx)
        else:
            # 같은 케이스의 여러 문단 → 서브 헤더로 묶기
            st.markdown(
                f'<div style="margin-top:0.75rem; padding: 0.3rem 0.6rem; '
                f'background:#f0f4ff; border-left:3px solid #4c7ef3; '
                f'border-radius:4px; font-size:0.85em; color:#2d4a8a; font-weight:600;">'
                f'📎 {_esc(case_group_title)}</div>',
                unsafe_allow_html=True,
            )
            for idx, doc in group_items:
                _render_document_expander(doc, doc_index=idx)


def _apply_cluster_first_bonus(docs: list[dict]) -> list[dict]:
    """동일 prefix 클러스터(1115-B, 1115-IE 등) 내 최저 번호 문단에 score 10% 보너스.

    K-IFRS 구조 특성: 도입·원칙 조항이 세부 처리 조항보다 앞 번호에 위치.
    (예: B20=도입, B21=핵심규정, B22~B27=세부처리 → B20·B21 우대)
    변경 1(rerank 쿼리 분리)로 해결 안 될 때의 타이브레이커 역할.
    클러스터 내 문단이 2개 이상일 때만 적용 (단독 문단은 보너스 없음).
    """
    from collections import defaultdict

    prefix_groups: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for doc in docs:
        cid = doc.get("chunk_id", "")
        m = re.match(r"^([\w]+-[A-Z]{0,2})(\d+)$", cid)
        if m:
            prefix_groups[m.group(1)].append((int(m.group(2)), cid))

    # 2개 이상 문단이 있는 클러스터의 최저 번호 chunk_id만 수집
    first_cids: set[str] = set()
    for items in prefix_groups.values():
        if len(items) >= 2:
            first_cids.add(min(items, key=lambda x: x[0])[1])

    return [
        {**doc, "score": doc.get("score", 0.0) * 1.1}
        if doc.get("chunk_id") in first_cids
        else doc
        for doc in docs
    ]


def _render_evidence_panel() -> None:
    """카테고리별 아코디언 문서 목록을 렌더링합니다.

    evidence 화면과 ai_answer Split View 양쪽에서 재사용합니다.
    - 섹션별로 상위 5개 문서만 초기 표시
    - 6개 이상이면 토글 버튼으로 나머지 펼쳐보기
    """
    docs: list[dict] = st.session_state.get("evidence_docs", [])

    if not docs:
        st.info("검색된 문서가 없습니다.")
        return

    # 화면 렌더링 직전에 문단 번호(paraNum)에서 숫자만 추출하여 오름차순 정렬
    def _extract_num(doc: dict) -> int:
        para_str = _get_doc_para_num(doc)
        m = re.search(r"\d+", para_str)
        return int(m.group()) if m else 999999

    docs = sorted(docs, key=_extract_num)

    # 문서를 그룹명별로 분류합니다.
    # source 값이 어느 그룹에도 없으면 "기타" 그룹으로 넣습니다.
    groups: dict[str, list[dict]] = {g: [] for g in ACCORDION_GROUPS}
    groups["기타"] = []

    for doc in docs:
        placed = False
        for group_name, sources in ACCORDION_GROUPS.items():
            if doc.get("source", "") in sources:
                groups[group_name].append(doc)
                placed = True
                break
        if not placed:
            groups["기타"].append(doc)

    # 그룹별 렌더링 (문서가 있는 그룹만 표시)
    for group_name, group_docs in groups.items():
        if not group_docs:
            continue

        total_count = len(group_docs)
        st.markdown(f"**{group_name}** — {total_count}건")

        # cluster-first 보너스 적용 후 점수 재정렬
        # (같은 prefix 클러스터의 최저 번호 문단 → 도입·핵심 조항 우선)
        group_docs = _apply_cluster_first_bonus(group_docs)
        group_docs.sort(key=lambda d: d.get("score", 0.0), reverse=True)

        core_docs = []
        context_docs = []

        if group_docs:
            max_score = group_docs[0].get("score", 0.0)

            # 검색 캐시로 인해 score 필드가 모두 0.0이거나 없는 경우 예외 처리 (기존처럼 상위 5개 분리)
            if max_score > 0.0:
                # 최대 점수의 80% 이상을 핵심 문단으로 분류
                threshold = max_score * 0.8
                for d in group_docs:
                    if d.get("score", 0.0) >= threshold:
                        core_docs.append(d)
                    else:
                        context_docs.append(d)
            else:
                core_docs = group_docs[:5]
                context_docs = group_docs[5:]

        # 문단 번호 기준으로 오름차순 정렬
        core_docs.sort(key=_extract_num)
        context_docs.sort(key=_extract_num)

        # 1. 핵심 문단 렌더링
        if core_docs:
            st.markdown("##### ⭐ 핵심 관련 문단")
            _render_docs_with_ie_grouping(core_docs, idx_offset=0)

        # 2. 관련 문단(나머지) 렌더링 (expander 내부)
        if context_docs:
            if core_docs:
                st.divider()

            with st.expander(
                f"📂 관련 조항 모두 펼쳐보기 ({len(context_docs)}건)", expanded=False
            ):
                st.markdown(
                    """
                    <style>
                    [data-testid="stExpander"] {
                        margin-bottom: 0.75rem !important;
                    }
                    /* 컨테이너 내부의 마지막 expander 마진 제거로 깔끔하게 */
                    [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stExpander"]:last-of-type {
                        margin-bottom: 0 !important;
                    }
                    </style>
                    """,
                    unsafe_allow_html=True,
                )
                with st.container(border=True):
                    _render_docs_with_ie_grouping(context_docs, idx_offset=len(core_docs))

        st.html("<br>")
