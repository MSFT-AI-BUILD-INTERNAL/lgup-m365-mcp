# Copilot Studio ↔ APIM OAuth2 연동 가이드

Microsoft Copilot Studio 에이전트가 Azure API Management(APIM)를 통해 MCP 서버에 OAuth 2.0 기반으로 연동하는 전체 절차를 안내합니다.

> **참고 문서**
> - [Secure access to MCP servers in Azure API Management](https://learn.microsoft.com/en-us/azure/api-management/secure-mcp-servers)
> - [Copilot Camp Lab MCS10 — MCP server with OAuth 2.0](https://microsoft.github.io/copilot-camp/pages/make/copilot-studio/10-mcp-oauth/)
> - [Configure user authentication with Microsoft Entra ID](https://learn.microsoft.com/en-us/microsoft-copilot-studio/configuration-authentication-azure-ad)

---

## 목차

1. [사전 조건](#1-사전-조건)
2. [Entra ID App Registration 구성 (2개)](#2-entra-id-app-registration-구성)
3. [인프라 배포](#3-인프라-배포)
4. [배포 검증](#4-배포-검증)
5. [Copilot Studio 에이전트 설정](#5-copilot-studio-에이전트-설정)
6. [E2E 테스트](#6-e2e-테스트)
7. [트러블슈팅](#7-트러블슈팅)

---

## 1. 사전 조건

| 항목 | 설명 |
|------|------|
| Azure 구독 | API Management, Container Apps 리소스 배포 권한 |
| Azure CLI | `az` 명령어 사용 가능, 로그인 완료 |
| Entra ID 권한 | App Registration 생성/수정 권한 (Application Administrator 또는 Global Admin) |
| Copilot Studio 라이선스 | Microsoft 365 Copilot Studio 접근 권한 |
| Node.js 20+ | 로컬 빌드 시 필요 |
| ACR (Azure Container Registry) | 컨테이너 이미지 푸시용 (사전 생성 필요) |

---

## 2. Entra ID App Registration 구성

공식 가이드에 따라 **두 개**의 App Registration이 필요합니다:

| 앱 | 역할 | 용도 |
|---|------|------|
| **MCP Server 앱** (Backend) | API 리소스 | APIM/Container App이 토큰을 검증할 때 사용하는 audience |
| **Copilot Studio Client 앱** (Frontend) | OAuth 클라이언트 | Copilot Studio가 토큰을 요청할 때 사용하는 client_id/secret |

### 앱 값 매핑 테이블 (한눈에 보기)

> ⚠️ **핵심**: 같은 앱을 Client와 Server 양쪽에 사용하면 `AADSTS90009` 오류가 발생합니다. 반드시 분리하세요.

| 설정 위치 | 필드명 | 어떤 앱의 값? | 예시 값 |
|-----------|--------|--------------|---------|
| **Bicep 파라미터** | `authClientId` | 🔵 Server 앱 | `c33af128-ff89-43c8-9d00-fec530e86e0d` |
| **APIM validate-jwt** | `audiences` | 🔵 Server 앱 | `api://c33af128-...`, `c33af128-...` |
| **Container App Easy Auth** | `clientId` | 🔵 Server 앱 | `c33af128-...` |
| **Container App Easy Auth** | `allowedAudiences` | 🔵 Server 앱 | `api://c33af128-...` |
| **Container App 환경변수** | `AUTH_CLIENT_ID` | 🔵 Server 앱 | `c33af128-...` |
| **Entra ID Expose an API** | Application ID URI | 🔵 Server 앱 | `api://c33af128-...` |
| **Entra ID Expose an API** | Scope | 🔵 Server 앱 | `access_as_user` |
| | | | |
| **Copilot Studio MCP Tool** | Client ID | 🟠 Client 앱 | `a1b2c3d4-...` (별도 앱) |
| **Copilot Studio MCP Tool** | Client Secret | 🟠 Client 앱 | `***` |
| **Copilot Studio MCP Tool** | Authorization URL | 테넌트 공통 | `https://login.microsoftonline.com/{tenantId}/oauth2/v2.0/authorize` |
| **Copilot Studio MCP Tool** | Token URL | 테넌트 공통 | `https://login.microsoftonline.com/{tenantId}/oauth2/v2.0/token` |
| **Power Automate Connector** | Client ID | 🟠 Client 앱 | `a1b2c3d4-...` |
| **Power Automate Connector** | Client Secret | 🟠 Client 앱 | `***` |
| **Power Automate Connector** | Resource URL | 🔵 Server 앱 | `api://c33af128-...` (scope 붙이지 않음!) |
| **Power Automate Connector** | Scope | 🔵 Server 앱에 정의된 scope | `access_as_user` (이름만) |
| | | | |
| **Entra ID Client 앱** | API permissions | 🔵 Server 앱의 scope를 위임 | `lgup-mcp-server/access_as_user` |
| **Entra ID Client 앱** | Redirect URI | Copilot Studio가 자동 생성 | (5-5에서 복사) |

**요약 규칙:**
- 🔵 **Server 앱** = "누구의 API를 보호하느냐" → audience, Resource URL, APIM 정책, Bicep 파라미터
- 🟠 **Client 앱** = "누가 토큰을 요청하느냐" → Copilot Studio의 Client ID/Secret, Power Automate Connector

### 2-1. MCP Server 앱 등록 (Backend)

1. [Microsoft Entra admin center](https://entra.microsoft.com) → **App registrations** → **+ New registration**
2. 설정:
   - **Name**: `lgup-mcp-server`
   - **Supported account types**: `Accounts in this organizational directory only`
   - **Redirect URI**: 비워둠
3. **Register** 클릭
4. **Application (client) ID**와 **Directory (tenant) ID**를 기록
   - 이 값이 Bicep의 `authClientId`와 `authTenantId`에 해당

#### API 노출 (Expose an API) 설정

1. 앱 → **Expose an API** → Application ID URI 옆 **Add** 클릭
2. 기본값 `api://{client-id}` 확인 후 **Save**

#### Scope 추가

1. **Expose an API** → **+ Add a scope**

| 필드 | 값 |
|------|-----|
| Scope name | `access_as_user` |
| Who can consent? | `Admins and users` |
| Admin consent display name | `Access MCP API as user` |
| Admin consent description | `Allows Copilot Studio to call the MCP API on behalf of a user` |
| State | `Enabled` |

2. **Add scope** 클릭
3. 전체 scope URI 확인: `api://{server-client-id}/access_as_user`

### 2-2. Copilot Studio Client 앱 등록 (Frontend)

1. **App registrations** → **+ New registration**
2. 설정:
   - **Name**: `lgup-mcp-copilot-client`
   - **Supported account types**: `Accounts in this organizational directory only`
   - **Redirect URI**: 비워둠 (Step 5에서 Copilot Studio가 자동 생성하는 URI를 추가)
3. **Register** 클릭
4. **Application (client) ID**를 기록

#### Client Secret 생성

1. 앱 → **Certificates & secrets** → **+ New client secret**
2. Description: `copilot-studio-mcp`, Expires: 조직 정책에 따라
3. **Add** 클릭 후 **Value** 즉시 복사

> ⚠️ **Secret Value는 생성 직후에만 표시됩니다. 반드시 즉시 복사하세요.**

#### API 권한 부여 (MCP Server 앱에 대한 접근 허용)

1. 앱 → **API permissions** → **+ Add a permission**
2. **APIs my organization uses** 탭 → `lgup-mcp-server` 검색 후 선택
3. **Delegated permissions** 선택 → `access_as_user` 체크 → **Add permissions**
4. 추가로 **Microsoft Graph** → **Delegated permissions** 추가:
   - `openid`, `profile`, `email`, `User.Read`
5. **Grant admin consent for [테넌트]** 클릭 → **Yes**

---

## 3. 인프라 배포

### 3-1. 파라미터 파일 준비

```bash
cp main.dev.bicepparam.example main.dev.bicepparam
```

주요 파라미터 편집:

```bicep
// MCP Server 앱의 Application (client) ID (Backend 앱)
param authClientId = '{2-1에서 기록한 Server 앱 Client ID}'

// Copilot Studio 환경 정보
param copilotStudio = {
  tenantId: '{Entra 테넌트 ID}'
  copilotStudioEnvironment: '{Copilot Studio 환경 ID}'
}

// 통합 엔드포인트
param integrations = {
  apimGatewayUrl: 'https://apim.example.com'
  ngisBaseUrl: 'https://ngis.example.com'
  pssBaseUrl: 'https://pss.example.com'
  tiroBaseUrl: 'https://tiro.example.com'
  confluenceBaseUrl: 'https://confluence.example.com'
  drmApiBaseUrl: 'https://drm.example.com'
}
```

> **중요**: `authClientId`는 **MCP Server 앱** (Backend)의 ID입니다. Copilot Studio Client 앱의 ID가 아닙니다.

### 3-2. Bicep 인프라 배포

```bash
# (선택) API 키 설정
export NGIS_API_KEY='{NGIS API Key}'
export DRM_API_KEY='{DRM API Key}'

# What-if 로 변경사항 미리보기
./deploy-bicep.sh --what-if

# 실제 배포
./deploy-bicep.sh
```

> **참고**: Client Secret은 Copilot Studio UI에서만 입력합니다. 서버에 배포하지 않습니다.

배포되는 리소스:
- Log Analytics Workspace + Application Insights
- User-Assigned Managed Identity
- Container Apps Environment + Container App (부트스트랩 이미지)
- API Management (Consumption 티어) — JWT 검증 정책 (`access_as_user` scope 포함)

### 3-3. 앱 이미지 배포

```bash
# AcrPull 권한을 Managed Identity에 수동 부여 (최초 1회)
MANAGED_IDENTITY_PRINCIPAL_ID=$(az deployment sub show \
  --name lgup-mcp-deploy \
  --query "properties.outputs.managedIdentityPrincipalId.value" -o tsv)

ACR_ID=$(az acr show --name {ACR이름} --resource-group {리소스그룹} --query id -o tsv)

az role assignment create \
  --assignee-object-id "$MANAGED_IDENTITY_PRINCIPAL_ID" \
  --assignee-principal-type ServicePrincipal \
  --role AcrPull \
  --scope "$ACR_ID"

# 앱 빌드 및 배포
./deploy-app.sh
```

---

## 4. 배포 검증

```bash
APIM_URL=$(az deployment sub show \
  --name lgup-mcp-deploy \
  --query "properties.outputs.apimGatewayUrl.value" -o tsv)
echo "APIM Gateway: $APIM_URL"
```

### 4-1. Health 엔드포인트

```bash
curl -s "$APIM_URL/health" | jq .
# 기대 응답: { "status": "ok", "server": "hanik-mcp-server", "version": "1.0.0" }
```

### 4-2. OAuth Protected Resource Metadata (RFC 9728)

```bash
curl -s "$APIM_URL/.well-known/oauth-protected-resource" | jq .
```

### 4-3. 토큰 획득 및 MCP 호출 테스트

```bash
# Client 앱의 credentials로 토큰 획득
TOKEN=$(curl -s -X POST \
  "https://login.microsoftonline.com/{tenantId}/oauth2/v2.0/token" \
  -d "client_id={client-앱-id}" \
  -d "client_secret={client-앱-secret}" \
  -d "scope=api://{server-앱-id}/.default" \
  -d "grant_type=client_credentials" | jq -r .access_token)

# MCP 도구 목록 요청
curl -s -X POST "$APIM_URL/mcp" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}' | jq .
```

---

## 5. Copilot Studio 에이전트 설정

Copilot Studio에서 MCP 서버를 **MCP Tool**로 직접 등록합니다 (Custom Connector가 아님).

### 5-1. 에이전트 생성/선택

1. [Copilot Studio](https://copilotstudio.microsoft.com) 접속
2. 에이전트 선택 또는 새 에이전트 생성

### 5-2. MCP Tool 추가

1. 에이전트 → **Tools** → **+ Add a tool**
2. **Create new** 섹션에서 **Model Context Protocol** 선택

### 5-3. MCP 서버 기본 정보 입력

| 필드 | 값 |
|------|-----|
| Server name | `LGUP MCP Server` (또는 적절한 이름) |
| Server description | MCP 서버 설명 |
| URL | `https://{apim-gateway-url}/mcp` (APIM Gateway URL + /mcp 경로) |

### 5-4. OAuth 2.0 인증 설정

1. Authentication 방식으로 **OAuth 2.0** 선택
2. **Manual** 선택 (수동 설정)

| OAuth 2.0 필드 | 값 | 설명 |
|----------------|-----|------|
| Client ID | `{client-앱-id}` | **Copilot Studio Client 앱** (2-2)의 Application ID |
| Client Secret | `{client-앱-secret}` | **Copilot Studio Client 앱**의 Secret |
| Authorization URL | `https://login.microsoftonline.com/{tenantId}/oauth2/v2.0/authorize` | Entra ID 인증 엔드포인트 |
| Token URL | `https://login.microsoftonline.com/{tenantId}/oauth2/v2.0/token` | Entra ID 토큰 엔드포인트 |
| Refresh URL | `https://login.microsoftonline.com/{tenantId}/oauth2/v2.0/token` | Token URL과 동일 |
| Scopes | `openid profile email` | 초기 scope (아래 5-6에서 실제 scope 추가) |

> **⚠️ 주의**: Client ID는 **MCP Server 앱이 아닌**, **Copilot Studio Client 앱**의 ID입니다.

3. **Create** 클릭

### 5-5. Redirect URI를 Client 앱에 등록

MCP Tool 생성 후 Copilot Studio가 **Redirect URL**을 자동 생성합니다. 이 URI를 🟠 Client 앱에 등록하지 않으면 `AADSTS500113: No reply address is registered` 오류가 발생합니다.

#### Redirect URL 찾기

1. Copilot Studio에서 5-4에서 생성한 MCP Tool의 설정 화면을 엽니다
2. **Connection** 섹션 아래 또는 OAuth 설정 영역에 **Redirect URL**이 표시됩니다
3. 이 URL을 **전체 복사**합니다
   - 일반적인 형식: `https://global.consent.azure-apim.net/redirect` 또는 Copilot Studio 고유 URI

> **참고**: Redirect URL은 Copilot Studio가 자동으로 생성합니다. 직접 추정하거나 임의로 입력하면 안 됩니다. 반드시 UI에 표시된 값을 그대로 사용하세요.

#### Entra ID Client 앱에 등록

1. [Microsoft Entra admin center](https://entra.microsoft.com) 접속
2. **Applications** → **App registrations** → **lgup-mcp-copilot-client** (🟠 Client 앱) 선택
3. 왼쪽 메뉴에서 **Authentication** 클릭
4. **+ Add a platform** → **Web** 선택
5. **Redirect URIs** 필드에 복사한 URL 붙여넣기
6. **Configure** 클릭

#### 등록 확인

- Authentication 페이지의 **Web** → **Redirect URIs** 목록에 방금 추가한 URI가 표시되어야 합니다
- 등록 후 Copilot Studio로 돌아가서 연결을 다시 시도하세요

### 5-6. Power Automate Connector에서 실제 Scope 설정

환경에 따라 Power Automate에서 추가 설정이 필요할 수 있습니다:

1. [Power Automate](https://make.powerautomate.com) 접속 → 올바른 환경 선택
2. **More** → **Discover all** → **Custom connectors**
3. MCP Tool과 동일한 이름의 커넥터 찾기 → **Edit** (연필 아이콘)
4. **Security** 탭 → **Edit**:

| 필드 | 값 |
|------|-----|
| Client Secret | Client 앱의 secret 재입력 |
| Resource URL | `api://{server-앱-id}` (MCP Server 앱의 Application ID URI) |
| Scope | `access_as_user` |

5. **Update connector** 클릭

### 5-7. 연결 완료

1. Copilot Studio로 돌아가서 MCP Tool 설정 화면의 **Connection** 섹션 확인
2. **Not connected** → **Create new connection** 클릭
3. Entra ID 로그인 화면에서 유효한 사용자 계정으로 인증
4. 권한 동의 → 연결 완료 (녹색 체크 표시)
5. **Add and configure** 클릭

### 5-8. 에이전트에서 Tool 활성화

MCP Tool 추가 후 사용 가능한 도구 목록이 표시됩니다:
- `test_hanik`
- `get_current_user`

에이전트 **Publish** 후 테스트 진행

---

## 6. E2E 테스트

### 6-1. Copilot Studio 대화 테스트

1. Copilot Studio **Test** 패널 열기
2. 첫 호출 시 **Allow** 버튼으로 사용자 인증 동의
3. 연결이 만료된 경우 **Open connection manager** → **Connect**로 재인증
4. 테스트 대화:
   - "테스트 해줘" → `test_hanik` → "test hanik mcp ok"
   - "내 정보 알려줘" → `get_current_user` → 인증된 사용자 정보 반환

### 6-2. 인증 흐름 확인 포인트

| 체크 항목 | 확인 방법 |
|-----------|----------|
| 토큰의 audience가 Server 앱 ID와 일치 | APIM에서 401이 아닌 200 반환 |
| `access_as_user` scope 포함 | APIM 401 / MCP 서버 403 확인 |
| 사용자 정보 전달 | `get_current_user` 결과에 displayName, email 포함 |
| SSE 스트리밍 동작 | MCP 도구 호출 응답이 정상 수신 |

---

## 7. 트러블슈팅

### 401 Unauthorized (APIM)

**원인**: JWT 검증 실패

- audience가 `api://{server-앱-id}` 또는 `{server-앱-id}`와 일치하지 않음
- 토큰이 만료됨
- issuer가 올바른 테넌트가 아님

**해결**:
```bash
# 토큰 디코딩하여 claims 확인
echo $TOKEN | cut -d'.' -f2 | base64 -d 2>/dev/null | jq .
# aud, iss, exp, scp 필드 확인
```

### 403 Forbidden (MCP Server)

**원인**: 토큰에 `access_as_user` scope가 없음

- Client 앱에 Server 앱의 `access_as_user` delegated permission이 부여되지 않음
- Admin consent가 완료되지 않음

**해결**:
1. Entra ID → **lgup-mcp-copilot-client** → **API permissions** 확인
2. `lgup-mcp-server`의 `access_as_user` 권한이 있는지 확인
3. Admin consent가 부여되었는지 확인 (녹색 체크)

### AADSTS500011: resource principal not found

**오류 메시지**: `The resource principal named api://{id}/access_as_user was not found in the tenant`

**원인**: Power Automate Connector의 Resource URL 또는 Scope 필드에 값이 잘못 입력됨. Power Platform은 내부적으로 `{Resource URL}/{Scope}`를 결합하여 토큰을 요청하므로, scope까지 포함된 URI를 Resource URL에 넣으면 이중 결합이 발생.

**해결**: Power Automate → Custom Connectors → Security 탭에서 필드를 올바르게 분리:

| 필드 | ✅ 올바른 값 | ❌ 잘못된 값 |
|------|-------------|-------------|
| Resource URL | `api://{server-앱-id}` | `api://{server-앱-id}/access_as_user` |
| Scope | `access_as_user` | `api://{server-앱-id}/access_as_user` |

**확인 포인트**:
1. Entra ID → MCP Server 앱 → **Expose an API** → Application ID URI가 `api://{server-앱-id}` 형식인지 확인
2. Resource URL에는 `/access_as_user`를 붙이지 않음
3. Scope에는 `api://` prefix 없이 scope 이름만 입력

### Copilot Studio에서 "Connection failed"

1. APIM Gateway URL이 공개 접근 가능한지 확인
2. **Redirect URI**가 Client 앱에 등록되었는지 확인 (5-5 참조)
3. Power Automate Connector의 **Resource URL**과 **Scope**가 설정되었는지 확인 (5-6 참조)
4. Copilot Studio와 APIM이 같은 Entra ID 테넌트인지 확인

### "Open connection manager" 반복 표시

**원인**: 토큰 만료 또는 Redirect URI 미등록

**해결**: 5-5의 Redirect URI 등록 확인 → 재연결

---

## 아키텍처 다이어그램

```
Copilot Studio Agent
        │
        │  Client 앱 (lgup-mcp-copilot-client)의
        │  client_id/secret으로 Entra ID에
        │  Authorization Code Flow 요청
        │
        ├──→ Entra ID ──→ access_token 발급
        │     (audience: api://{server-앱-id})
        │     (scope: access_as_user)
        │
        │  Authorization: Bearer {access_token}
        ▼
┌──────────────────────────────────────────────┐
│ Azure API Management (Consumption)           │
│                                              │
│  validate-jwt:                               │
│   • audience: api://{server-앱-id}            │
│   • scope: access_as_user                    │
│   • JWKS: Entra ID OpenID Configuration      │
│                                              │
│  buffer-response: false (SSE 지원)            │
└──────────────────┬───────────────────────────┘
                   │ forward-request
                   ▼
┌──────────────────────────────────────────────┐
│ Container App (hanik-mcp-server)             │
│                                              │
│  Easy Auth: x-ms-client-principal 헤더 주입   │
│  Scope 검증 (defence-in-depth)               │
│  MCP Tools: test_hanik, get_current_user     │
└──────────────────────────────────────────────┘
```

### 핵심 구분: 두 개의 App Registration

```
┌─────────────────────────────┐    ┌─────────────────────────────┐
│  MCP Server 앱 (Backend)    │    │  Copilot Client 앱 (Frontend)│
│  lgup-mcp-server            │    │  lgup-mcp-copilot-client    │
│                             │    │                             │
│  • Expose an API            │◄───│  • API Permissions:         │
│  • Scope: access_as_user    │    │    Server/access_as_user    │
│  • Bicep: authClientId      │    │  • Client Secret            │
│  • APIM audience 검증용     │    │  • Copilot Studio에 입력    │
└─────────────────────────────┘    └─────────────────────────────┘
```
