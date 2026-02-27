# kifrs.com 페이지 HTML 구조 파악

import requests
from bs4 import BeautifulSoup

URL = "https://www.kifrs.com/s/1115"  # K-IFRS 1115호 메인
headers = {"User-Agent": "Mozilla/5.0"}

res = requests.get(URL, headers=headers)
res.encoding = "utf-8"
soup = BeautifulSoup(res.text, "html.parser")

# HTML 저장
with open("data/web/kifrs_1115_page.html", "w", encoding="utf-8") as f:
    f.write(soup.prettify())

print(f"✅ 상태코드: {res.status_code}")
print(f"   HTML 저장 완료: data/web/kifrs-1115-page.html")

# 목차 링크 구조 파악
print("\n── 링크 구조 (상위 20개) ──")
for a in soup.find_all("a", href=True)[:20]:
    href = a["href"]
    text = a.get_text(strip=True)[:50]
    if "/s/1115" in href:
        print(f"  {href}  →  {text}")