# app/ui/topic_browse.py
# 토픽 브라우즈 유틸리티 — 토픽 설명 HTML 포맷팅
#
# pinpoint_panel.py에서 섹션 설명을 HTML로 렌더링할 때 사용합니다.

import html as _html


def _format_desc_html(desc: str) -> str:
    """토픽 설명 텍스트를 안전한 HTML로 변환합니다.

    줄바꿈을 <br>로 변환하고, XSS 방지를 위해 HTML 이스케이프합니다.
    """
    if not desc:
        return ""
    escaped = _html.escape(desc)
    return escaped.replace("\n", "<br>")
