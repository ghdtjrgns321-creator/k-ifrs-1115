# app/ui/components.py
# 후방 호환 barrel — 기존 import 경로를 유지하기 위한 re-export.
#
# 실제 구현:
#   doc_helpers.py   — 순수 Python 헬퍼 (Streamlit 의존 없음)
#   doc_renderers.py — 개별 문서 Streamlit 렌더링
#   evidence.py      — 카테고리별 아코디언 패널

from app.ui.doc_helpers import (  # noqa: F401
    _apply_cluster_first_bonus,
    _build_self_ids,
    _convert_journal_entries,
    _format_pdr_content,
    _get_doc_para_num,
    _ie_para_sort_key,
    _is_ie_doc,
    _normalize_case_group_title,
)
from app.ui.doc_renderers import (  # noqa: F401
    _render_document_expander,
    _render_docs_with_ie_grouping,
    _render_para_chips,
    _render_pdr_expander,
)
from app.ui.evidence import _render_evidence_panel  # noqa: F401
