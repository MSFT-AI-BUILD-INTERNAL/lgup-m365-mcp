# lgup-ax-mcp-server (Python)

TypeScript MCP 서버(`../app`)를 **Python으로 포팅**한 구현입니다. 공식 **MCP Python SDK**(Streamable HTTP)로 MCP 프로토콜을 처리하고, 나머지 엔드포인트는 **FastAPI**로 구현했으며, DDD 바운디드 컨텍스트 구조를 그대로 유지합니다.

## 구성 (DDD 바운디드 컨텍스트)

```
src/hanik_mcp/
  main.py                    # Composition Root (FastAPI + MCP 마운트)
  shared/                    # Shared Kernel
    server_info.py           # 서버 식별/포트/정적파일 경로
    entra_settings.py        # EntraSettings 값객체
  identity/                  # 신원/접근제어 컨텍스트
    access_token.py          # AccessToken 값객체 (JWT 클레임/스코프)
    caller_identity.py       # ACL: EasyAuth 헤더/Bearer → 도메인 신원
    scope_guard.py           # 스코프 정책 (401/403)
  mcp_server/                # MCP 컨텍스트
    server.py                # FastMCP + 도구(test_lgup, get_current_user)
  drm/                       # DRM 복호화 컨텍스트
    credentials.py           # DrmCredentials 값객체 (env)
    signature.py             # DrmSignature 값객체 (SEULGI-HMAC-SHA256)
    decryption_client.py     # ACL: 외부 DRM API (httpx)
    routes.py                # /drm/decrypt
  oauth/
    metadata_routes.py       # /.well-known/*
  presentation/
    ui_routes.py             # /auth-ui, /drm-ui, /vendor, /auth-ui/config
    templates/*.html         # 로그인/복호화 테스트 UI (정적 템플릿)
    static/msal-browser.min.js  # 로컬 제공 MSAL 번들
```

## 엔드포인트

| 경로 | 설명 |
|------|------|
| `POST /mcp` | Streamable HTTP MCP 엔드포인트 (도구: `test_lgup`, `get_current_user`) |
| `GET /auth-ui` | Entra 로그인 + MCP API 테스트 UI |
| `GET /drm-ui` | 로그인 게이트 → DRM/MIP 복호화 테스트 UI |
| `POST /drm/decrypt` | 서버측 HMAC 서명 후 외부 DRM API로 프록시 |
| `GET /.well-known/oauth-protected-resource` | RFC 9728 메타데이터 |
| `GET /.well-known/oauth-authorization-server` | RFC 8414 메타데이터 |
| `GET /health` | 헬스 체크 |

## 로컬 실행

```bash
# 1) 가상환경 + 의존성
uv venv --python 3.13
source .venv/bin/activate
uv pip install -e .

# 2) 환경변수 (Entra)
export AUTH_TENANT_ID='<tenant-guid>'
export AUTH_CLIENT_ID='<api-app-client-id>'

# (선택) DRM 복호화 자격정보 — 커밋 금지
export DRM_HOST='seulgiapi.lguplus.co.kr'
export DRM_CLIENT_ID='<x-client-id>'
export DRM_KEY_ID='<x-key-id>'
export DRM_SECRET_KEY='<hmac-secret>'
export DRM_USER_EMAIL='<user-email>'
export DRM_USER_LOGINID='<user-loginId>'

# 3) 실행
PORT=8080 python -m hanik_mcp.main
# 또는: PORT=8080 hanik-mcp
```

브라우저에서 `http://localhost:8080/drm-ui` 또는 `/auth-ui` 접속.

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

## TS 버전과의 동등성

- 모든 보조 엔드포인트 상태코드/응답 형태 동일 (health/auth-ui/drm-ui/config/vendor/well-known, `/mcp` 401·403, `/drm/decrypt` 401·503·400·502).
- DRM HMAC-SHA256 서명은 Node 구현과 **바이트 단위 동일**함을 교차 검증.
- MCP 프로토콜은 공식 SDK를 사용하므로 Copilot Studio 등 실제 MCP 클라이언트와 호환.

## 보안

- 시크릿(DRM secretKey 등)은 **환경변수로만** 사용되며 브라우저로 전달되지 않습니다.
- HMAC 서명·외부 API 호출은 서버(`/drm/decrypt`)에서 수행합니다.
- MSAL은 외부 CDN 대신 **로컬 정적 파일**로 제공합니다.
