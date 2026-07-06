# HWP/HWPX AI 전처리 (`preprocess_hwp.py`)
 
폴더 안의 `.hwp` / `.hwpx` 문서를 자동으로 읽어서 AI가 읽기 좋은 형태로
정제하는 순수 Python 스크립트입니다. (기존 Excel 리본(VBA) + DRM 복호화
빌드에서 "전처리" 로직만 분리해 재구성했습니다.)
 
## 결과물
 
파일마다:
- `<파일명>.md`   : 사람/AI 둘 다 읽기 좋은 정제 텍스트(Markdown, 제목/문단/표)
- `<파일명>.json` : 에이전트가 쓰기 좋은 구조화 데이터
 
그리고 전체 처리 결과를 모은 `outputs/_summary.json` 을 함께 만듭니다.
 
## 설치
 
```bash
pip install -r requirements.txt
```
 
- `.hwp` (구형 바이너리) 추출에는 오픈소스 `pyhwp` 가 필요합니다(`hwp5txt` CLI 우선,
  실패 시 `hwp5` 파이썬 API 로 폴백).
- `.hwpx` (신형 ZIP+XML) 는 표준 라이브러리(zipfile + xml)만으로 처리하므로
  추가 패키지가 필요 없습니다.
 
## 사용법
 
```bash
python preprocess_hwp.py <입력폴더|파일>
python preprocess_hwp.py <입력폴더|파일> --out <출력폴더>
```
 
결과는 기본적으로 이 스크립트와 같은 폴더의 `outputs/` 에 저장됩니다.
 
## DRM(보안문서) 연동 지점
 
이 파일은 **순수 전처리 로직만** 담고 있습니다. 사내 MIP DRM 복호화 구조
(엑셀 리본 + VBA + 복호화 API 연동)는 별도로 관리되는 부분이라 여기에는
포함하지 않았고, 대신 다음과 같은 "플러그인 지점"만 남겨 두었습니다.
 
- 스크립트와 같은 폴더(또는 `PYTHONPATH`)에 사내 `mip_decrypt.py` 모듈을
  두면 자동으로 감지해서 사용합니다. 모듈이 없으면 DRM 문서는 안내 메시지와
  함께 건너뛰고 일반 문서만 처리합니다.
- `mip_decrypt` 모듈이 만족해야 하는 최소 인터페이스:
  - `mip_decrypt.load_context(base_dir) -> MipClient | None`
  - `MipClient.decrypt_file(path) -> bytes` (복호화된 평문 바이트 반환)
- 처리 흐름(`process_file`)은 "DRM 감지 → (있으면) 복호화 호출 → 평문을
  임시파일에 써서 → 전처리 실행 → 임시파일 삭제" 순서로 이미 연결되어
  있으므로, 실제 사내 복호화 모듈만 옆에 두면 별도 코드 수정 없이 한 번에
  동작합니다.
 
## 검증
 
`extract_hwpx` 로 뽑은 결과를 기존 exe 빌드가 만든 참고 출력(`outputs/*.json`)과
비교했을 때 `blocks` / `char_count` / `block_counts` 가 완전히 동일함을
확인했습니다 (DRM 복호화 단계만 제외하고 전처리 로직 자체는 동일하게 동작).