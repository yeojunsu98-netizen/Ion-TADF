# Ion-TADF literature search

GitHub Actions로 **2020년 이후 ionic / charged TADF 관련 논문**을 과거까지 검색하는 저장소입니다.

검색 소스:
- OpenAlex
- Crossref
- Semantic Scholar
- arXiv

결과:
- `results/ion_tadf_2020_present.csv`
- `results/ion_tadf_2020_present.md`

## 실행
GitHub에서 **Actions → Historical Ion-TADF search → Run workflow** 를 누르면 됩니다.

검색 결과는 DOI / arXiv ID / 제목으로 중복 제거한 뒤, TADF와 ionic/charged/counterion/LEC 관련성이 함께 있는 논문만 남깁니다.
