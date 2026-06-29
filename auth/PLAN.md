# Auth Module 구현 계획

## 목적

Microsoft Entra ID 기반 인증을 통해 MCP 서버(`/mcp` 엔드포인트)를 보호한다.  
현재 MCP 서버(`app/src/index.ts`)는 인증 없이 동작하며, 토큰 디코딩만 수행하고 서명 검증은 하지 않는다.  
이 모듈은 **토큰 검증을 포함한 인증 서버**를 구현하여, 검증된 요청만 MCP 서버에 도달하도록 한다.

---

## 인증 시나리오 (2가지)

### 시나리오 A: Copilot Studio → OAuth 연동 (Entra ID)

```
[Copilot Studio] 
    ↓ (1) 사용자 동의 후 Entra ID에서 access_token 획득
    ↓ (2) Authorization: Bearer <token> 헤더로 MCP 서버 호출
[Auth Server] 
    ↓ (3) Entra ID JWKS로 토큰 서명 검증 + audience/issuer/scope 검증
    ↓ (4) 검증 성공 시 요청을 MCP 서버로 프록시 (또는 미들웨어로 통과)
[MCP Server /mcp]
```

- Copilot Studio는 **Confidential Client** 또는 **On-behalf-of (OBO)** 흐름으로 토큰을 획득
- 토큰의 `aud`는 MCP 서버의 App ID URI (`api://<client-id>`)
- `scp` 클레임에 `access_as_user` 스코프가 포함되어야 함

### 시나리오 B: 모바일 앱 → PKCE (Public Client)

```
[모바일 앱 (iOS/Android)]
    ↓ (1) Authorization Code + PKCE 로 Entra ID에서 access_token 획득
    ↓ (2) Authorization: Bearer <token> 헤더로 MCP 서버 호출
[Auth Server]
    ↓ (3) 동일한 JWKS 검증 로직 (audience/issuer/scope)
    ↓ (4) 검증 성공 시 MCP 서버로 요청 전달
[MCP Server /mcp]
```

- 모바일 앱은 **Public Client + PKCE** (Authorization Code Flow with PKCE)
- Entra App Registration에 모바일 플랫폼 Redirect URI 등록 필요
- 토큰 형식은 시나리오 A와 동일 → 검증 로직도 동일

---

## 아키텍처 결정사항

### 옵션: Reverse Proxy vs Express Middleware

| 방식 | 장점 | 단점 |
|------|------|------|
| **독립 Auth Proxy 서버** | MCP 서버 코드 변경 없음, 관심사 분리 | 네트워크 홉 추가, 배포 복잡도 증가 |
| **Express Middleware** | 단일 프로세스, 지연시간 최소 | MCP 서버에 의존성 추가 |

**선택: Express Middleware 방식** (auth 모듈을 미들웨어 패키지로 구현)

- 이유: 현재 `app/src/index.ts`가 Express 기반이므로 미들웨어로 자연스럽게 통합 가능
- auth 폴더는 **독립적으로도 사용 가능한 인증 서버 + 미들웨어 라이브러리**로 구성
- 단독 실행 시 인증 프록시 서버로 동작하고, 임포트 시 미들웨어로 사용 가능

---

## 폴더 구조

```
auth/
├── PLAN.md                    # 이 문서
├── package.json               # 독립 패키지 (workspace 참조 가능)
├── tsconfig.json
├── .env.example               # 환경변수 템플릿
├── src/
│   ├── index.ts               # 진입점: 독립 서버 모드 (auth proxy)
│   ├── middleware.ts          # Express 미들웨어 (export for app/)
│   ├── token-validator.ts     # Entra ID JWT 검증 핵심 로직
│   ├── jwks-client.ts         # JWKS 키 캐싱 및 조회
│   ├── config.ts              # 환경변수 로드 및 검증
│   ├── types.ts               # 타입 정의 (AuthenticatedRequest 등)
│   └── errors.ts              # 인증 오류 클래스
├── test/
│   ├── token-validator.test.ts
│   ├── middleware.test.ts
│   └── fixtures/              # 테스트용 JWT, JWKS mock
│       ├── keys.ts
│       └── tokens.ts
└── Dockerfile                 # 독립 실행 시 컨테이너화
```

---

## 구현 상세

### 1. `config.ts` — 환경변수 관리

```typescript
interface AuthConfig {
  tenantId: string;               // Entra Directory (Tenant) ID
  clientId: string;               // App Registration의 Application (Client) ID
  audience: string;               // 토큰의 aud 클레임 (기본: api://<clientId>)
  issuer: string;                 // 토큰의 iss 클레임 (v2.0 endpoint 기준)
  jwksUri: string;                // Entra JWKS endpoint
  requiredScopes: string[];       // 필수 스코프 (예: ['access_as_user'])
  allowedClientIds?: string[];    // 허용된 azp/appid (Copilot Studio 앱 ID 등)
  proxyTarget?: string;           // 독립 실행 시 MCP 서버 URL
  port: number;                   // Auth 서버 포트
}
```

환경변수:
```env
ENTRA_TENANT_ID=<tenant-id>
ENTRA_CLIENT_ID=<client-id>
ENTRA_AUDIENCE=api://<client-id>
ENTRA_REQUIRED_SCOPES=access_as_user
ENTRA_ALLOWED_CLIENT_IDS=<copilot-studio-app-id>,<mobile-app-id>
AUTH_PROXY_TARGET=http://localhost:8080
AUTH_PORT=3001
```

### 2. `jwks-client.ts` — JWKS 키 관리

- Entra ID의 OpenID Connect discovery endpoint에서 JWKS URI 조회:
  - `https://login.microsoftonline.com/{tenantId}/v2.0/.well-known/openid-configuration`
- JWKS 키를 메모리에 캐시 (TTL: 24시간, 키 미스 시 즉시 리프레시)
- 라이브러리: `jose` (경량, Node.js 네이티브 crypto 활용)

```typescript
import { createRemoteJWKSet } from 'jose';

// Entra v2.0 JWKS endpoint
const JWKS = createRemoteJWKSet(
  new URL(`https://login.microsoftonline.com/${tenantId}/discovery/v2.0/keys`)
);
```

### 3. `token-validator.ts` — JWT 검증 핵심

검증 항목:
1. **서명 검증** — JWKS에서 kid로 공개키 조회 후 RS256 서명 확인
2. **issuer 검증** — `https://login.microsoftonline.com/{tenantId}/v2.0`
3. **audience 검증** — `api://<client-id>` (또는 bare client-id)
4. **만료 검증** — `exp` 클레임 (clock skew 허용: 5분)
5. **nbf 검증** — `nbf` (not before) 클레임
6. **scope 검증** — `scp` 클레임에 필수 스코프 포함 여부
7. **azp/appid 검증** (선택) — 호출자 앱 ID가 허용 목록에 있는지

```typescript
import { jwtVerify, type JWTPayload } from 'jose';

interface ValidatedToken {
  payload: JWTPayload;
  userId: string;          // oid 또는 sub
  displayName: string;     // name 또는 preferred_username
  tenantId: string;        // tid
  scopes: string[];        // scp를 split한 배열
  clientAppId: string;     // azp 또는 appid
}

async function validateToken(token: string, config: AuthConfig): Promise<ValidatedToken>;
```

### 4. `middleware.ts` — Express 미들웨어

```typescript
import { type Request, type Response, type NextFunction } from 'express';

/**
 * Entra ID 토큰 검증 미들웨어.
 * Authorization: Bearer <token> 헤더에서 토큰을 추출하고 검증한다.
 * 검증 성공 시 req.auth에 ValidatedToken을 첨부한다.
 * 실패 시 401/403 응답을 반환한다.
 */
export function entraAuthMiddleware(config: AuthConfig) {
  return async (req: Request, res: Response, next: NextFunction) => {
    // 1. Authorization 헤더에서 Bearer 토큰 추출
    // 2. validateToken() 호출
    // 3. 성공: req.auth = validatedToken, next()
    // 4. 실패: 401 Unauthorized (토큰 없음/만료/서명 무효)
    //         403 Forbidden (스코프 부족/비허용 클라이언트)
  };
}
```

특이사항:
- `/health` 등 헬스체크 경로는 인증 제외
- OPTIONS (CORS preflight)도 인증 제외
- `x-ms-client-principal` 헤더(Easy Auth)도 보조적으로 지원

### 5. `index.ts` — 독립 Auth Proxy 서버

독립 실행 시 동작:
1. Express 서버를 AUTH_PORT에서 시작
2. 모든 요청에 entraAuthMiddleware 적용
3. 검증 성공한 요청을 `AUTH_PROXY_TARGET`(MCP 서버)으로 프록시
4. 프록시 시 원본 Authorization 헤더와 함께 `X-Auth-User-*` 커스텀 헤더 추가

```
[Client] → [Auth Proxy :3001] → (token 검증) → [MCP Server :8080]
```

### 6. `errors.ts` — 오류 처리

```typescript
class AuthenticationError extends Error {
  statusCode: 401;
  code: 'TOKEN_MISSING' | 'TOKEN_EXPIRED' | 'TOKEN_INVALID_SIGNATURE' | 'TOKEN_MALFORMED';
}

class AuthorizationError extends Error {
  statusCode: 403;
  code: 'INSUFFICIENT_SCOPE' | 'CLIENT_NOT_ALLOWED' | 'TENANT_MISMATCH';
}
```

---

## Entra App Registration 요구사항

### MCP 서버 앱 (리소스 서버)

| 항목 | 설정 |
|------|------|
| App ID URI | `api://<client-id>` |
| Expose an API | 스코프: `access_as_user` |
| Supported account types | 단일 테넌트 (조직 내부) |
| Token version | v2.0 |

### Copilot Studio 앱 (클라이언트 — 시나리오 A)

| 항목 | 설정 |
|------|------|
| API permissions | MCP 서버 앱의 `access_as_user` 위임된 권한 추가 |
| Client type | Confidential (client_secret 또는 certificate) |
| Grant type | Authorization Code 또는 On-Behalf-Of |

### 모바일 앱 (클라이언트 — 시나리오 B)

| 항목 | 설정 |
|------|------|
| API permissions | MCP 서버 앱의 `access_as_user` 위임된 권한 추가 |
| Client type | Public client |
| Authentication platform | Mobile and desktop applications |
| Redirect URI | `msauth://<bundle-id>/callback` 또는 커스텀 스킴 |
| Grant type | Authorization Code + PKCE |
| Allow public client flows | Yes |

---

## (추가 분석) 서버 엔드포인트 차이 — Copilot Studio vs PKCE 모바일

### 결론: Auth 서버 엔드포인트는 동일하다

두 시나리오 모두 최종적으로 **동일한 형태의 Entra ID v2.0 access token**을 `Authorization: Bearer <token>` 헤더에 담아 MCP 서버로 전송한다.  
따라서 auth 서버가 노출하는 엔드포인트와 검증 로직은 **한 벌**이면 충분하다.

```
┌─────────────────────────────────────────────────────────────┐
│                    Auth Server Endpoints                      │
├─────────────────────────────────────────────────────────────┤
│  POST /mcp        → Bearer 토큰 검증 → MCP 서버로 프록시     │
│  GET  /health     → 인증 없이 200 OK (헬스체크)              │
│  GET  /.well-known/oauth-protected-resource (선택)           │
│                   → 클라이언트에게 인증 메타데이터 제공        │
└─────────────────────────────────────────────────────────────┘
```

### 왜 동일한가? — 토큰 관점 비교

| 관점 | Copilot Studio (시나리오 A) | 모바일 PKCE (시나리오 B) |
|------|----------------------------|------------------------|
| **토큰 발급자** | Entra ID v2.0 | Entra ID v2.0 |
| **토큰 전달 방식** | `Authorization: Bearer <token>` | `Authorization: Bearer <token>` |
| **aud (audience)** | `api://<mcp-server-client-id>` | `api://<mcp-server-client-id>` |
| **iss (issuer)** | `https://login.microsoftonline.com/{tid}/v2.0` | 동일 |
| **scp (scope)** | `access_as_user` | `access_as_user` |
| **토큰 유형** | 위임된 사용자 토큰 (delegated) | 위임된 사용자 토큰 (delegated) |
| **azp (authorized party)** | Copilot Studio 앱의 Client ID | 모바일 앱의 Client ID |
| **서명 알고리즘** | RS256 (Entra JWKS) | RS256 (Entra JWKS) |

**유일한 차이**: `azp`(또는 `appid`) 클레임의 값이 다르다.  
→ auth 서버는 `ENTRA_ALLOWED_CLIENT_IDS` 환경변수에 두 Client ID를 모두 등록하면 된다.

### 세부 차이점 및 대응

| 차이점 | 설명 | Auth 서버 대응 |
|--------|------|----------------|
| **azp 값** | Copilot Studio 앱 ID vs 모바일 앱 ID | `allowedClientIds` 배열에 양쪽 모두 포함 |
| **토큰 수명** | Copilot Studio는 보통 1시간, 모바일도 동일 | 차이 없음 (exp 검증은 동일) |
| **추가 헤더** | Copilot Studio가 `x-ms-client-principal` 추가 전송 가능 | 보조 정보로 활용 (필수 아님) |
| **CORS** | 모바일은 CORS 불필요, 웹 프론트엔드 추가 시 필요 | 기본 비활성, 필요 시 Origin 화이트리스트 |
| **토큰 갱신** | Copilot Studio: 자동 갱신, 모바일: MSAL이 refresh_token으로 갱신 | Auth 서버 관여 없음 (클라이언트 책임) |

### 선택적 엔드포인트: OAuth Protected Resource Metadata

MCP 2025 스펙에서는 리소스 서버가 인증 요구사항을 광고할 수 있다.  
필수는 아니지만, 클라이언트 자동 설정을 위해 아래 엔드포인트를 추가할 수 있다:

```
GET /.well-known/oauth-protected-resource
```

응답 예시:
```json
{
  "resource": "api://<mcp-server-client-id>",
  "authorization_servers": [
    "https://login.microsoftonline.com/<tenant-id>/v2.0"
  ],
  "scopes_supported": ["access_as_user"],
  "bearer_methods_supported": ["header"]
}
```

이 엔드포인트는 인증 없이 접근 가능하며, 두 시나리오 모두 동일한 응답을 반환한다.

---

## (추가 분석) 클라이언트 측 작업 가이드

### 시나리오 A: Copilot Studio 측 설정 작업

Copilot Studio에서 MCP 서버를 OAuth 보호된 커넥터로 연결하려면 다음 작업이 필요하다:

#### A-1. Entra ID App Registration (Copilot Studio용 클라이언트 앱)

> ⚠️ MCP 서버 앱과는 **별도의** App Registration이다.

| 단계 | 작업 | 상세 |
|------|------|------|
| 1 | App Registration 생성 | 이름: `copilot-studio-mcp-client` (자유) |
| 2 | Client Secret 생성 | Certificates & secrets → New client secret → 값 복사 |
| 3 | API 권한 추가 | API permissions → Add → My APIs → MCP 서버 앱 선택 → `access_as_user` 위임 권한 체크 |
| 4 | 관리자 동의 부여 | Grant admin consent (테넌트 관리자) |
| 5 | Redirect URI 설정 | Web 플랫폼: `https://token.botframework.com/.auth/web/redirect` |

#### A-2. Copilot Studio 내 OAuth 연결 구성

Copilot Studio 관리 포털에서:

| 단계 | 작업 | 설정값 |
|------|------|--------|
| 1 | Settings → Security → Authentication | "Authenticate with Microsoft" 또는 커스텀 OAuth |
| 2 | OAuth Connection 생성 | Service Provider: `Azure Active Directory v2` |
| 3 | Client ID | Copilot Studio용 앱의 Application (Client) ID |
| 4 | Client Secret | A-1에서 생성한 secret 값 |
| 5 | Tenant ID | 조직 Directory (Tenant) ID |
| 6 | Scope | `api://<mcp-server-client-id>/access_as_user` |
| 7 | Token Exchange URL (SSO) | `api://<copilot-studio-app-id>` (SSO 사용 시) |

#### A-3. Copilot Studio에서 MCP 커넥터 등록

| 단계 | 작업 | 설정값 |
|------|------|--------|
| 1 | Actions → Add an action → MCP Server | 선택 |
| 2 | Server URL | `https://<mcp-server-domain>/mcp` |
| 3 | Authentication | 위에서 만든 OAuth Connection 선택 |
| 4 | Auth Header | `Authorization: Bearer {token}` (자동 구성) |

#### A-4. 동작 흐름 (런타임)

```
[사용자] → [Copilot Studio 채팅]
    ↓ (1) 사용자 인증 (Entra SSO 또는 명시적 로그인)
[Copilot Studio] → [Entra ID token endpoint]
    ↓ (2) Authorization Code → access_token 획득
         scope: api://<mcp-server-client-id>/access_as_user
[Copilot Studio] → [MCP Server /mcp]
    ↓ (3) POST /mcp + Authorization: Bearer <access_token>
[Auth Server] 
    ↓ (4) JWKS 서명 검증 + aud/iss/scp 확인
    ↓ (5) 성공 → MCP 응답 반환
[사용자] ← [도구 실행 결과]
```

---

### 시나리오 B: 모바일 앱 (PKCE) 측 작업

#### B-1. Entra ID App Registration (모바일 클라이언트 앱)

| 단계 | 작업 | 상세 |
|------|------|------|
| 1 | App Registration 생성 | 이름: `mobile-mcp-client` (자유) |
| 2 | Authentication → Platform 추가 | "Mobile and desktop applications" 선택 |
| 3 | Redirect URI | iOS: `msauth://<bundle-id>//auth`<br>Android: `msauth://<package-name>/<signature-hash>` |
| 4 | Public client 허용 | Authentication → Advanced → "Allow public client flows" = **Yes** |
| 5 | API 권한 추가 | API permissions → Add → My APIs → MCP 서버 앱 → `access_as_user` |
| 6 | 관리자 동의 (선택) | 사용자 동의가 허용된 테넌트면 불필요 |

> ⚠️ 모바일 앱은 **Public Client**이므로 Client Secret을 사용하지 않는다.  
> PKCE(code_verifier + code_challenge)로 Authorization Code 교환을 보호한다.

#### B-2. 모바일 앱 코드 구현 (MSAL 라이브러리)

**iOS (Swift — MSAL for iOS)**
```swift
import MSAL

let config = MSALPublicClientApplicationConfig(
    clientId: "<mobile-app-client-id>",
    redirectUri: "msauth://<bundle-id>//auth",
    authority: try MSALAADAuthority(
        url: URL(string: "https://login.microsoftonline.com/<tenant-id>")!
    )
)
let application = try MSALPublicClientApplication(configuration: config)

let parameters = MSALInteractiveTokenParameters(
    scopes: ["api://<mcp-server-client-id>/access_as_user"],
    webviewParameters: MSALWebviewParameters(authPresentationViewController: self)
)

application.acquireToken(with: parameters) { result, error in
    guard let result = result else { return }
    let accessToken = result.accessToken
    // → 이 토큰을 MCP 서버 호출 시 Bearer 헤더에 포함
}
```

**Android (Kotlin — MSAL for Android)**
```kotlin
val config = PublicClientApplication.createSingleAccountPublicClientApplication(
    context,
    R.raw.msal_config  // JSON config with clientId, redirectUri, authority
)

val scopes = arrayOf("api://<mcp-server-client-id>/access_as_user")
config.acquireToken(activity, scopes) { result ->
    val accessToken = result.accessToken
    // → 이 토큰을 MCP 서버 호출 시 Bearer 헤더에 포함
}
```

**msal_config.json (Android)**
```json
{
  "client_id": "<mobile-app-client-id>",
  "authorization_user_agent": "DEFAULT",
  "redirect_uri": "msauth://<package-name>/<signature-hash>",
  "authorities": [{
    "type": "AAD",
    "audience": { "type": "AzureADMyOrg", "tenant_id": "<tenant-id>" }
  }]
}
```

#### B-3. 모바일 앱에서 MCP 서버 호출

```
// HTTP 요청 예시
POST https://<mcp-server-domain>/mcp
Authorization: Bearer <access_token>
Content-Type: application/json
Accept: application/json, text/event-stream

{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": { "name": "test_hanik", "arguments": {} }
}
```

#### B-4. 동작 흐름 (런타임)

```
[모바일 앱] → [시스템 브라우저 / WebView]
    ↓ (1) PKCE: code_verifier 생성 → code_challenge 계산 (S256)
[모바일 앱] → [Entra ID /authorize]
    ↓ (2) GET /authorize?response_type=code&code_challenge=...&scope=api://.../access_as_user
[사용자] → [Entra 로그인 화면에서 인증]
    ↓ (3) Redirect → msauth://<bundle-id>//auth?code=<authorization_code>
[모바일 앱] → [Entra ID /token]
    ↓ (4) POST /token: code + code_verifier → access_token 반환
[모바일 앱] → [MCP Server /mcp]
    ↓ (5) POST /mcp + Authorization: Bearer <access_token>
[Auth Server]
    ↓ (6) JWKS 서명 검증 + aud/iss/scp 확인
    ↓ (7) 성공 → MCP 응답 반환
[모바일 앱] ← [도구 실행 결과]
```

#### B-5. 토큰 갱신 (Silent Refresh)

- MSAL 라이브러리가 `refresh_token`을 내부적으로 관리
- `acquireTokenSilently()` 호출 시 만료 전 자동 갱신
- Auth 서버는 갱신 과정에 관여하지 않음 (클라이언트 ↔ Entra ID 직접 통신)

---

### 종합 비교: 클라이언트별 작업 요약

| 작업 영역 | Copilot Studio (A) | 모바일 PKCE (B) | Auth 서버 |
|-----------|--------------------|--------------------|-----------|
| Entra App Registration | Confidential Client 생성 | Public Client 생성 | 리소스 서버 앱 (API 노출) |
| Client Secret | 필요 (secret 또는 cert) | 불필요 (PKCE 보호) | 불필요 |
| Redirect URI | Bot Framework URL | msauth:// 스킴 | 해당 없음 |
| 토큰 획득 주체 | Copilot Studio 런타임 | 모바일 앱 (MSAL) | 토큰 미발급 (검증만) |
| 토큰 전달 방식 | Bearer 헤더 (자동) | Bearer 헤더 (개발자 구현) | 동일하게 수신 |
| 사용자 개입 | Entra SSO / 1회 동의 | 앱 내 로그인 화면 | 해당 없음 |
| 토큰 갱신 | Copilot 자동 처리 | MSAL silent refresh | 관여 안 함 |
| CORS 필요 | 아니오 (서버→서버) | 아니오 (네이티브 앱) | CORS 미설정 |
| Auth 서버 추가 엔드포인트 | 없음 | 없음 | `/mcp` + `/health` 만 |

---

## 의존성 (Dependencies)

```json
{
  "dependencies": {
    "jose": "^5.x",                    // JWT 검증 (JWKS, RS256)
    "express": "^4.21.x",             // HTTP 서버
    "http-proxy-middleware": "^3.x",   // 독립 실행 시 프록시
    "dotenv": "^16.x"                  // 환경변수 로드
  },
  "devDependencies": {
    "@types/express": "^4.17.x",
    "@types/node": "^22.x",
    "typescript": "^5.7.x",
    "vitest": "^3.x"                   // 테스트
  }
}
```

- `jose`: `jsonwebtoken` + `jwks-rsa` 조합 대비 의존성 최소, ESM 지원, Node.js crypto 네이티브 활용
- 별도 MSAL 라이브러리 불필요 (서버 측에서는 토큰 *검증*만 수행하므로)

---

## 통합 방안 (app/ 폴더와의 관계)

### 방안 1: 미들웨어로 직접 임포트 (권장, 단일 프로세스)

```typescript
// app/src/index.ts 수정
import { entraAuthMiddleware } from '../../auth/src/middleware.js';

app.use('/mcp', entraAuthMiddleware(config));
app.post('/mcp', async (req, res) => { /* MCP 처리 */ });
```

### 방안 2: 사이드카 / 별도 컨테이너 (마이크로서비스)

- Kubernetes/Container Apps에서 auth 컨테이너를 사이드카로 배치
- Ingress → Auth Container → MCP Container

### 방안 3: Azure Container Apps Easy Auth (플랫폼 네이티브)

- Container Apps의 내장 인증을 활성화하면 별도 코드 없이 Entra 검증 가능
- 단, 세밀한 scope/claims 검증은 앱 코드에서 추가로 필요

**추천 조합**: Easy Auth(1차 차단) + 미들웨어(세밀한 scope/claims 검증)

---

## 구현 순서 (우선순위)

| # | 작업 | 설명 |
|---|------|------|
| 1 | 프로젝트 초기화 | `auth/package.json`, `tsconfig.json`, 의존성 설치 |
| 2 | `config.ts` | 환경변수 로드/검증, AuthConfig 타입 정의 |
| 3 | `jwks-client.ts` | Entra JWKS 조회 + 캐싱 (`jose` createRemoteJWKSet) |
| 4 | `token-validator.ts` | JWT 검증 로직 (서명, iss, aud, exp, scp) |
| 5 | `types.ts` + `errors.ts` | 공통 타입, 에러 클래스 |
| 6 | `middleware.ts` | Express 미들웨어 (Bearer 추출 → 검증 → req.auth) |
| 7 | `index.ts` | 독립 실행 Auth Proxy 서버 |
| 8 | 테스트 | vitest 기반 단위/통합 테스트 |
| 9 | app/ 통합 | `app/src/index.ts`에 미들웨어 적용 |
| 10 | Dockerfile | auth 모듈 컨테이너화 |
| 11 | 문서화 | .env.example, README (설정 가이드) |

---

## 보안 고려사항

- **토큰 서명은 반드시 검증**: 현재 `app/src/index.ts`의 `decodeJwtClaims()`는 서명 미검증. 운영 환경에서는 반드시 JWKS 기반 검증 필수.
- **HTTPS 강제**: 프로덕션에서 Bearer 토큰은 TLS 위에서만 전송
- **토큰 캐싱 금지**: access_token을 서버에 저장하지 않음 (stateless 검증)
- **Clock skew 허용**: 시계 차이 최대 5분 (`clockTolerance`)
- **Rate limiting**: 토큰 검증 실패 시 429 응답으로 brute force 방어
- **로깅**: 검증 실패 시 토큰 내용은 로깅하지 않음 (oid, tid만 기록)
- **CORS**: 모바일 앱 Origin은 불필요, 웹 클라이언트 추가 시 Origin 허용 목록 관리

---

## 테스트 전략

1. **단위 테스트** (`token-validator.test.ts`)
   - 유효한 토큰 → 성공
   - 만료된 토큰 → TOKEN_EXPIRED
   - 잘못된 서명 → TOKEN_INVALID_SIGNATURE  
   - audience 불일치 → TOKEN_INVALID
   - scope 부족 → INSUFFICIENT_SCOPE

2. **통합 테스트** (`middleware.test.ts`)
   - 토큰 없는 요청 → 401
   - 유효한 토큰 → next() 호출 + req.auth 설정
   - /health 요청 → 인증 우회

3. **E2E 테스트** (수동/CI)
   - 실제 Entra ID에서 발급한 토큰으로 MCP 서버 호출
   - Copilot Studio에서 MCP 도구 호출 → 사용자 정보 반환 확인

---

## 참고: Entra ID v2.0 토큰 구조

```json
{
  "aud": "api://xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "iss": "https://login.microsoftonline.com/{tenant-id}/v2.0",
  "iat": 1719619200,
  "nbf": 1719619200,
  "exp": 1719623100,
  "azp": "yyyyyyyy-yyyy-yyyy-yyyy-yyyyyyyyyyyy",
  "name": "홍길동",
  "oid": "zzzzzzzz-zzzz-zzzz-zzzz-zzzzzzzzzzzz",
  "preferred_username": "gildong@contoso.com",
  "scp": "access_as_user",
  "sub": "...",
  "tid": "{tenant-id}",
  "ver": "2.0"
}
```

---

## 완료 기준

- [ ] `auth/` 폴더가 독립적으로 빌드 가능 (`npm run build` 성공)
- [ ] 단위 테스트 통과 (`npm test` 성공)
- [ ] 유효한 Entra 토큰으로 MCP 엔드포인트 호출 시 정상 응답
- [ ] 무효한 토큰으로 호출 시 401/403 응답
- [ ] Copilot Studio에서 OAuth 연동 후 MCP 도구 호출 성공
- [ ] 모바일 PKCE 토큰으로 MCP 도구 호출 성공
