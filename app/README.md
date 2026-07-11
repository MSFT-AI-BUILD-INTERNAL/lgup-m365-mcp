# lgup-ax-mcp-server (Python)

lgup-m365-mcp 의 **MCP 서버(Python)** 구현입니다. 공식 **MCP Python SDK**(Streamable HTTP)로 MCP 프로토콜을 처리하고, 나머지 엔드포인트는 **FastAPI**로 구현했으며, DDD 바운디드 컨텍스트 구조를 따릅니다.

## 구성 (DDD 바운디드 컨텍스트)

```
src/
  main.py                    # Composition Root (FastAPI + MCP 마운트)
  shared/                    # Shared Kernel
    server_info.py           # 서버 식별/포트/정적파일 경로
    entra_settings.py        # EntraSettings 값객체
  identity/                  # 신원/접근제어 컨텍스트
    access_token.py          # AccessToken 값객체 (JWT 클레임/스코프)
    caller_identity.py       # ACL: EasyAuth 헤더/Bearer → 도메인 신원
    scope_guard.py           # 스코프 정책 (401/403)
    entra_token_validator.py # Entra JWKS 기반 JWT 서명/issuer/audience 검증
    auth_middleware.py       # 보호 엔드포인트 공통 인증 미들웨어
  mcp_server/                # MCP 컨텍스트
    server.py                # FastMCP + 도구(test_lgup, get_current_user)
  drm/                       # DRM 복호화 컨텍스트
    credentials.py           # DrmCredentials 값객체 (env)
    signature.py             # DrmSignature 값객체 (SEULGI-HMAC-SHA256)
    decryption_client.py     # ACL: 외부 DRM API (httpx)
    routes.py                # /drm/decrypt
  oauth/
    metadata_routes.py       # /.well-known/*
  test_ui/                   # 테스트 전용 프론트엔드 (프로덕션 표면 아님)
    ui_routes.py             # /auth-ui, /drm-ui, /vendor, /auth-ui/config
    templates/*.html         # 로그인/복호화 테스트 UI (정적 템플릿)
    static/msal-browser.min.js  # 로컬 제공 MSAL 번들
```

> **테스트 프론트엔드 분리**: `test_ui/`의 브라우저 페이지들은 API/MCP를 브라우저에서
> 시험하기 위한 **개발·테스트 전용**입니다. 실제 서비스 표면(API/MCP)과 분리되어 있으며,
> `ENABLE_TEST_UI` 환경변수가 설정된 경우에만 마운트됩니다(기본 비활성). 실제 클라이언트는
> `POST /drm/decrypt`(API)와 `POST /mcp`(MCP)를 직접 호출합니다.

## 엔드포인트

### 프로덕션 표면 (항상 제공)

| 경로 | 설명 |
|------|------|
| `POST /mcp` | Streamable HTTP MCP 엔드포인트 (도구: `test_lgup`, `get_current_user`) |
| `POST /drm/decrypt` | 서버측 HMAC 서명 후 외부 DRM API로 프록시 |
| `GET /.well-known/oauth-protected-resource` | RFC 9728 메타데이터 |
| `GET /.well-known/oauth-authorization-server` | RFC 8414 메타데이터 |
| `GET /health` | 헬스 체크 |

### 테스트 전용 프론트엔드 (`ENABLE_TEST_UI=1` 일 때만 제공)

| 경로 | 설명 |
|------|------|
| `GET /auth-ui` | Entra 로그인 + MCP API 테스트 UI |
| `GET /drm-ui` | 로그인 게이트 → DRM/MIP 복호화 테스트 UI |
| `GET /auth-ui/config` | 테스트 UI 설정(Tenant/Client/Scope) |
| `GET /vendor/msal-browser.min.js` | 로컬 제공 MSAL 번들 |

## 로컬 실행

```bash
# 1) 가상환경 + 의존성 (app/ 디렉터리에서)
uv venv --python 3.13
source .venv/bin/activate
uv pip install -r requirements.txt

# 2) 환경변수 (Entra)
export AUTH_TENANT_ID='<tenant-guid>'
export AUTH_CLIENT_ID='<api-app-client-id>'
# (선택) JWT 키셋 URL 오버라이드. 기본은 Entra discovery 키셋.
# 테스트/특수 게이트웨이 시나리오에서만 사용.
export AUTH_JWKS_URI='<jwks-uri>'

# (테스트 전용) 브라우저 테스트 UI 활성화 — 프로덕션에서는 설정하지 말 것
export ENABLE_TEST_UI=1

# (선택) DRM 복호화 자격정보 — 커밋 금지
export DRM_HOST='seulgiapi.lguplus.co.kr'
export DRM_CLIENT_ID='<x-client-id>'
export DRM_KEY_ID='<x-key-id>'
export DRM_SECRET_KEY='<hmac-secret>'
export DRM_USER_EMAIL='<user-email>'
export DRM_USER_LOGINID='<user-loginId>'

# 3) 실행 (app/ 디렉터리에서)
PORT=8080 python -m src.main
# 또는: PORT=8080 uvicorn src.main:app --host 0.0.0.0 --port 8080
```

브라우저에서 `http://localhost:8080/drm-ui` 또는 `/auth-ui` 접속. (테스트 UI는 `ENABLE_TEST_UI=1` 일 때만 열립니다.)

## 테스트 (curl)

```bash
# 헬스
curl http://localhost:8080/health

# MCP 도구 호출 (유효 토큰 필요)
curl -X POST http://localhost:8080/mcp \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"test_lgup","arguments":{}}}'
# => "test lgup mcp ok"
```

## CLI 도구

```bash
# HWP/HWPX 전처리 (docs/tool/preprocess_hwp.py 로직 이식)
python -m src.preprocess <폴더|파일> --out <출력폴더>
#  → 각 문서를 <name>.md / <name>.json 으로 정제, _summary.json 요약 생성
#  (.hwp 는 pyhwp/hwp5txt, .hwpx 는 표준 라이브러리 — pyhwp 는 requirements.txt 에 포함되어 둘 다 지원)

# 프로그램적으로 호출 (모듈 API)
#   from src.preprocess import preprocess_file, preprocess_document, preprocess_path

# DRM 파일 복호화 (환경변수 DRM_* 필요)
python -m src.drm.cli <암호화파일> --out <출력파일>
```

## 자동화 테스트 (pytest)

테스트는 `src` 밖의 `tests/` 에 있습니다.

```bash
# 테스트 의존성 설치 (pytest, playwright) + 브라우저
uv pip install -e '.[dev]'          # 또는: pip install -e '.[dev]'
python -m playwright install chromium

pytest                               # 전체
pytest tests/test_preprocess_cli.py  # 1) hwp/hwpx 전처리 CLI
pytest tests/test_decrypt_cli.py     # 2) 복호화 CLI (httpx.MockTransport 모킹)
pytest tests/test_entra_login_e2e.py # 3) Entra 로그인 e2e (Playwright)
```

| 파일 | 대상 |
|------|------|
| `tests/test_preprocess_cli.py` | `python -m src.preprocess` — HWPX 실제 파싱, HWP 추출기 모킹, 실패/요약 검증 |
| `tests/test_decrypt_cli.py` | `python -m src.drm.cli` — DRM API를 `httpx.MockTransport`로 모킹해 정상호출(서명 헤더/엔드포인트)·응답(복호화 바이트) 검증 |
| `tests/test_entra_login_e2e.py` | 실서버 기동 후 헤드리스 Chromium으로 `/auth-ui` 로그인 → MS authorize 리다이렉트(client_id/redirect_uri/scope/PKCE) 검증. Playwright/브라우저 없으면 자동 skip |

## 참고 (구현 이력)


- 초기 구현은 TypeScript였으나 Python으로 전환했습니다. 엔드포인트/인증/APIM 정책은 동일합니다.
- DRM HMAC-SHA256 서명은 이전 Node 구현과 **바이트 단위 동일**함을 교차 검증했습니다.
- MCP 프로토콜은 공식 SDK를 사용하므로 Copilot Studio 등 실제 MCP 클라이언트와 호환됩니다.

## 보안

- 시크릿(DRM secretKey 등)은 **환경변수로만** 사용되며 브라우저로 전달되지 않습니다.
- HMAC 서명·외부 API 호출은 서버(`/drm/decrypt`)에서 수행합니다.
- MSAL은 외부 CDN 대신 **로컬 정적 파일**로 제공합니다.
- 앱 미들웨어는 Entra JWT를 검증하며, Copilot Studio 연동에서 전달되는 `raw_jwt` 형태(`{header}.{payload}.[Signature]`)도 클레임 검증(issuer/aud/exp/scope)으로 처리합니다.
