# App 미들웨어 직접 인증 방식 가이드 (Copilot Studio 연동)

이 문서는 **현재 앱 구현(`app/src/identity/*`) 기준**으로, Container App 플랫폼 EasyAuth가 아니라 **앱 미들웨어에서 직접 Entra 토큰을 검증**해 Copilot Studio와 연동하는 방법을 정리합니다.

---

## 1) 현재 구현 요약

앱은 FastAPI HTTP 미들웨어에서 보호 경로를 판별하고 토큰을 검증합니다.

- 진입점: `app/src/main.py`의 `@app.middleware("http")`
- 인증 처리: `app/src/identity/auth_middleware.py`
- 토큰 검증: `app/src/identity/entra_token_validator.py`
- OAuth 메타데이터 제공: `app/src/oauth/metadata_routes.py`

핵심 동작:

- 보호 경로는 bearer token 필수, 실패 시 `401/403` 반환
- `/mcp`는 scope를 `access_as_user` **또는** `CopilotStudio.AgentNodes.Invoke` 중 하나 허용
- `/.well-known/oauth-protected-resource`, `/.well-known/oauth-authorization-server` 제공

---

## 2) 보호 경로/요구사항 (코드 기준)

`auth_middleware.py` 기준:

- 보호됨:
  - `POST /mcp` (단, `ALLOW_ANONYMOUS_MCP=true`면 예외)
  - `POST /drm/decrypt`
  - `POST /upload`
  - `/onedrive*`
- 공개:
  - `/health`
  - `/.well-known/*`
  - `/auth-ui`, `/drm-ui`, `/vendor/*`

scope 정책:

- `/mcp` `POST`: `["access_as_user", "CopilotStudio.AgentNodes.Invoke"]`
- 그 외 보호 경로: `["access_as_user"]`

---

## 3) Entra App Registration 구성 (직접 인증 방식)

EasyAuth와 동일하게 **Server 앱 + Client 앱 2개**를 사용합니다.

## 3-1. Server 앱 (API 리소스)

1. App Registration 생성 (Single tenant)
2. `Application (client) ID`, `Directory (tenant) ID` 확보
3. **Expose an API**
   - Application ID URI: `api://{server-client-id}`
   - Scope: `access_as_user` 생성

## 3-2. Client 앱 (Copilot Studio OAuth 클라이언트)

1. Client 앱 등록 + client secret 생성
2. API permissions에 Server 앱의 delegated permission `access_as_user` 추가
3. Admin consent 수행
4. Copilot Studio에서 생성된 Redirect URI를 Client 앱 Web Redirect URI에 등록

---

## 4) 앱 환경변수 (직접 인증에 필수)

앱 미들웨어 검증에 필요한 최소값:

- `AUTH_TENANT_ID={tenant-guid}`
- `AUTH_CLIENT_ID={server-app-client-id}`

옵션:

- `AUTH_JWKS_URI` (테스트/특수 게이트웨이용 JWKS override)
- `ALLOW_ANONYMOUS_MCP=true` (PoC용 무인증 MCP 허용, 운영 비권장)

`AUTH_CLIENT_ID`는 **Server 앱 ID**여야 합니다.

---

## 5) Copilot Studio 연결값 (앱 직접 인증 방식)

Copilot Studio MCP Tool/OAuth 2.0 설정:

- Client ID: **Client 앱** ID
- Client Secret: **Client 앱** secret
- Authorization URL: `https://login.microsoftonline.com/{tenantId}/oauth2/v2.0/authorize`
- Token URL: `https://login.microsoftonline.com/{tenantId}/oauth2/v2.0/token`
- Scope 권장: `api://{server-client-id}/access_as_user`

참고:

- 앱은 `/mcp`에서 `CopilotStudio.AgentNodes.Invoke` scope도 허용하도록 구현되어 있습니다.
- 또한 Copilot 전달 토큰 호환을 위해 `aud=https://api.powerplatform.com`도 수용합니다(`entra_token_validator.py`의 audience 후보).

---

## 6) 토큰 검증 상세 (현재 코드 동작)

`validate_entra_access_token()`이 아래를 검증합니다.

1. `Authorization: Bearer <token>` 형식
2. 만료/유효시각: `exp`, `nbf`
3. issuer:
   - `https://login.microsoftonline.com/{tenant}/v2.0`
   - `https://sts.windows.net/{tenant}/` (v1 형태도 허용)
4. audience:
   - `api://{AUTH_CLIENT_ID}`
   - `{AUTH_CLIENT_ID}`
   - `https://api.powerplatform.com`
5. scope/roles에 required scope 존재 여부

토큰 형식:

- 일반 JWT: Entra JWKS 서명 검증 수행
- Copilot raw 형식(`{header}.{payload}.[Signature]`): 서명 대신 핵심 claim 검증 수행

---

## 7) 검증 절차 (실전 체크)

1. OAuth 메타데이터 노출 확인

```bash
curl -s https://<app-url>/.well-known/oauth-protected-resource | jq .
curl -s https://<app-url>/.well-known/oauth-authorization-server | jq .
```

2. 토큰 없이 보호 API 호출 시 401 확인

```bash
curl -i https://<app-url>/upload
curl -i https://<app-url>/mcp -X POST -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

3. 유효 토큰으로 `/mcp` 호출

```bash
curl -s -X POST https://<app-url>/mcp \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | jq .
```

---

## 8) 사용자 정보(email 포함) 전달 방식

직접 인증 방식에서는 앱이 토큰 클레임에서 사용자 정보를 읽습니다.

- 구현 위치: `app/src/identity/caller_identity.py`
- 사용 필드:
  - `displayName`: `name`/`preferred_username`/`upn` fallback
  - `email`: `email` claim
  - `objectId`: `oid` 또는 `sub`

주의:

- `email` claim은 항상 보장되지 않습니다.
- 운영에서는 `email` 단독 의존 대신 `preferred_username`/`upn` fallback을 권장합니다.

---

## 9) EasyAuth 방식과 차이점

| 항목 | 앱 미들웨어 직접 인증 | Container App EasyAuth |
|---|---|---|
| 검증 위치 | 앱 코드(FastAPI 미들웨어) | 플랫폼(ACA authConfig) |
| 커스터마이징 | 높음(`/mcp`만 별도 scope, Copilot raw 포맷 허용 등) | 상대적으로 제한적 |
| 토큰 형식 대응 | 코드로 확장 가능 | 플랫폼 지원 범위 내 |
| 사용자 정보 접근 | 토큰 클레임(및 필요 시 EasyAuth 헤더도 해석 가능) | `x-ms-client-principal*`, `/.auth/me` 기본 제공 |
| 운영 부담 | JWKS/클레임 정책을 앱이 책임 | 플랫폼 설정 중심(앱 단순화) |
| 장애 영향 | 코드 배포/버그 영향 큼 | 설정 오류 영향 큼 |
| 권장 시나리오 | Copilot 특수 토큰/정책 커스터마이징 필요 시 | 표준 OAuth 보호 + 운영 단순화 우선 시 |

실무 권장:

- **표준화/운영 단순화**가 우선이면 EasyAuth 중심
- **Copilot 특수 요구(토큰 형식, 경로별 정책)**가 크면 앱 미들웨어 중심
- 혼합 운용 시에는 EasyAuth를 `AllowAnonymous`로 두고 최종 권한판단은 앱 미들웨어에서 일관되게 수행

---

## 10) 자주 나는 오류

- `401 Unauthorized`
  - `aud`, `iss`, `exp` 불일치/만료
  - `AUTH_CLIENT_ID`, `AUTH_TENANT_ID` 오설정
- `403 Forbidden`
  - required scope 미포함 (`access_as_user` 또는 `/mcp`의 Copilot scope)
- `AADSTS500113`
  - Client 앱 Redirect URI 미등록

### 10-1) `POST /mcp` 401 + `Unexpected token audience`

증상 예시:

- `wwwAuthenticate realm="api://7138..."`
- token claim `aud="api://c33a..."`
- token claim `appid="7138..."`

원인:

- **Server(API 리소스) 앱 ID와 Client(호출) 앱 ID가 뒤바뀐 설정**입니다.
- 미들웨어는 `aud`를 `AUTH_CLIENT_ID` 기준으로 검증하므로, `AUTH_CLIENT_ID`가 Server 앱 ID가 아니면 401이 발생합니다.

정상 정합성:

- `AUTH_CLIENT_ID` = **Server 앱** Client ID
- Copilot Studio OAuth Client ID/Secret = **Client 앱** 값
- Access token:
  - `aud` = `api://<Server 앱 ID>` (또는 `<Server 앱 ID>`)
  - `appid` = `<Client 앱 ID>`
  - `scp`에 `access_as_user` 또는 `CopilotStudio.AgentNodes.Invoke`

즉시 조치:

```bash
RG="<resource-group>"
APP="<container-app-name>"
TENANT_ID="d0a0ff17-cf70-4fc6-b2b9-ad659ff82b30"
SERVER_APP_ID="c33af128-ff89-43c8-9d00-fec530e86e0d"

az containerapp update \
  --resource-group "$RG" \
  --name "$APP" \
  --set-env-vars AUTH_TENANT_ID="$TENANT_ID" AUTH_CLIENT_ID="$SERVER_APP_ID"
```

참고:

- `deploy-app.sh`는 이미지/스토리지 env를 주로 갱신하며, `AUTH_*` 값 정합성은 별도 점검이 필요합니다.

검증:

```bash
# 1) 런타임 env 확인
az containerapp show -g "$RG" -n "$APP" \
  --query "properties.template.containers[0].env[?name=='AUTH_CLIENT_ID' || name=='AUTH_TENANT_ID']" \
  -o table

# 2) OAuth protected resource 메타데이터 확인
APP_URL="https://<app-fqdn>"
curl -s "$APP_URL/.well-known/oauth-protected-resource" | jq .
# 기대: resource == "api://c33af128-ff89-43c8-9d00-fec530e86e0d"

# 3) 재호출 후 로그 확인
az containerapp logs show -g "$RG" -n "$APP" --type console --tail 200
```

---

## 11) PoP(Proof-of-Possession) 토큰 심층 검토

### 결론 요약

- **EasyAuth 단독으로는 PoP 검증 요구를 충족하기 어렵습니다.**
- **앱 미들웨어에서 직접 구현하면 이론적으로 가능**하지만, 현재 코드에는 PoP 검증 로직이 없습니다.
- 또한 Copilot Studio/커넥터 호출 경로가 PoP용 증명(HTTP 바인딩 서명)을 안정적으로 전달하지 않으면, 앱에서 구현해도 실사용이 어렵습니다.

### 왜 Bearer 검증과 PoP 검증이 다른가

PoP 검증은 JWT 유효성(issuer/audience/signature)만으로 끝나지 않습니다. 리소스 서버는 추가로 아래를 확인해야 합니다.

1. 토큰의 `cnf`(confirmation)로 키 바인딩 확인
2. 요청 단위 증명값(메서드/호스트/경로/시각/nonce 등) 검증
3. 재전송(replay) 방지 정책(짧은 TTL + nonce 캐시) 적용

즉, 단순 `Authorization: Bearer` 검증 계층보다 구현/운영 복잡도가 크게 높습니다.

### 현재 앱 구현 대비 갭

현재 `entra_token_validator.py`는 다음 중심입니다.

- Bearer 형식 확인
- Entra JWKS 기반 서명 검증(일반 JWT)
- `iss` / `aud` / `exp` / `nbf` / scope 검증

현재 없는 것:

- `cnf` 기반 키 바인딩 검증
- 요청 바인딩 증명 검증(HTTP method/path/host 연계)
- nonce/재전송 방지 저장소

따라서 **현재 상태로는 PoP 토큰 보안 모델을 충족하지 못합니다.**

### 앱에서 구현한다면 필요한 아키텍처

1. 인증 미들웨어 확장
   - `Authorization` 스킴이 PoP/DPoP 계열인지 식별
   - proof 헤더 파싱 + 서명 검증
2. claim + 요청 컨텍스트 결합 검증
   - `cnf`의 키/지문과 proof 서명키 일치
   - proof claim과 실제 요청(`method`, `url`) 일치
3. anti-replay 계층 추가
   - `jti`/nonce 저장소(Redis 등) + 짧은 만료
4. 실패 처리 표준화
   - 401/403 + 상세 `WWW-Authenticate` 에러코드 분리

### Copilot Studio 연동 관점의 현실 체크

- 앱이 PoP를 검증하려면 **클라이언트(Copilot connector)가 PoP proof를 매 요청에 제공**해야 합니다.
- 커넥터가 Bearer만 전달하는 경우, 서버가 PoP를 강제하면 호출은 계속 실패합니다.
- 따라서 실제 적용 전, 먼저 “Copilot 경로에서 PoP proof 헤더를 보낼 수 있는지”를 PoC로 검증해야 합니다.

### 권장 전략

1. 단기: Bearer 기반(현재 방식) 안정화
   - scope 매핑 정합성 먼저 해결(현재 403의 1순위 원인)
2. 중기: PoP PoC 분기 구현
   - `/mcp`에 선택적 PoP 모드(feature flag) 도입
3. 장기: PoP 강제 전환
   - 클라이언트 지원이 확인된 경로부터 점진 전환
