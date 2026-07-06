# hanik-mcp-server

`test hanik mcp ok` 메시지를 반환하는 최소 MCP 서버입니다. Azure Container Apps(상위 `main.bicep`)로 배포되며, M365 Copilot Studio Agent와 Client Application에서 호출할 수 있도록 컨테이너화되어 있습니다.

## 구성

- **전송 방식:** Streamable HTTP (`POST /mcp`) — Copilot Studio Agent 또는 원격 Client Application에서 호출 가능
- **포트:** `PORT` 환경변수 (기본 `8080`, Bicep의 `containerPort`와 일치)
- **도구(tool):** `test_hanik` — 입력 없이 `"test hanik mcp ok"` 텍스트를 반환
- **헬스 체크:** `GET /health` — Container Apps probe용
- **인증 테스트 UI:** `GET /auth-ui` — Entra ID 로그인 후 토큰으로 `/mcp` API 호출 테스트
- **DRM 복호화 테스트 UI:** `GET /drm-ui` — Entra 로그인(게이트)을 먼저 통과한 뒤 파일을 업로드해 DRM/MIP 복호화 API 호출
- **DRM 프록시 엔드포인트:** `POST /drm/decrypt` — 서버가 HMAC 서명을 계산해 외부 DRM API로 전달(시크릿은 브라우저에 노출되지 않음)

## 로컬 실행

```bash
npm install
npm run build
PORT=8080 npm start
```

Entra ID 테스트 UI 사용 시 환경변수:

```bash
export AUTH_TENANT_ID='<tenant-guid>'
export AUTH_CLIENT_ID='<api-app-client-id>'
PORT=8080 npm start
```

브라우저에서 `http://localhost:8080/auth-ui` 접속 후 로그인/호출 테스트.

## DRM 복호화 테스트 UI (`/drm-ui`)

Entra 로그인 화면이 먼저 뜨고, 로그인에 성공해야 DRM 복호화 패널이 표시됩니다.
시크릿(secretKey 등)은 서버 환경변수로만 사용되며 브라우저로 전달되지 않습니다.
HMAC 서명 계산과 외부 API 호출은 서버(`POST /drm/decrypt`)에서 수행합니다.

필수 환경변수:

```bash
# Entra (로그인 게이트용)
export AUTH_TENANT_ID='<tenant-guid>'
export AUTH_CLIENT_ID='<api-app-client-id>'

# DRM/MIP decrypt API 자격정보 (커밋 금지, 로컬/시크릿 스토어에서 주입)
export DRM_HOST='seulgiapi.lguplus.co.kr'
export DRM_CLIENT_ID='<x-client-id>'
export DRM_KEY_ID='<x-key-id>'
export DRM_SECRET_KEY='<hmac-secret>'
export DRM_USER_EMAIL='<user-email>'
export DRM_USER_LOGINID='<user-loginId>'

PORT=8080 npm start
```

테스트 절차:

1. 브라우저에서 `http://localhost:8080/drm-ui` 접속 → Entra 로그인.
2. 로그인 성공 후 파일을 선택하고 `Decrypt 호출`.
3. 서버가 `host;clientId;keyId;timestamp;email;loginId` 문자열을 `DRM_SECRET_KEY`로 HMAC-SHA256 서명하여 `https://<DRM_HOST>/v1/mip/decrypt`로 파일을 전달하고, 복호화 결과는 브라우저에서 다운로드됩니다.

## Entra 로그인 + API 호출 UI 테스트 가이드

1. Entra App 등록(SPA)에서 Redirect URI를 추가합니다.
  - `http://localhost:8080/auth-ui`
  - 배포 환경도 테스트할 경우 `https://<your-app-domain>/auth-ui`
2. API 권한에서 `api://<AUTH_CLIENT_ID>/access_as_user` delegated scope를 사용자에게 부여하고 동의(Admin/User consent)합니다.
3. `/auth-ui`에서 로그인 후 기본 JSON-RPC payload로 `test_hanik` 호출을 테스트합니다.
4. `Call get_current_user` 버튼으로 전달된 사용자 클레임을 확인합니다.

테스트:

```bash
# 헬스 체크
curl http://localhost:8080/health

# MCP 도구 호출
curl -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"test_hanik","arguments":{}}}'
# => "test hanik mcp ok"
```

## 컨테이너 이미지 빌드 및 푸시 (ACR)

```bash
# 1) ACR에 빌드 + 푸시 (로컬 Docker 불필요)
az acr build \
  --registry <your-acr-name> \
  --image hanik-mcp-server:1.0.0 \
  .
```

## Bicep으로 배포

빌드한 이미지를 상위 스택의 파라미터로 전달합니다.

1. `../main.dev.bicepparam` 는 샘플로 유지하고, 실제 배포에는 이를 복사한 로컬 파일(예: `../main.local.bicepparam`)의 `containerImage` 를 푸시한 이미지로 설정:

   ```bicep
   param containerImage = '<your-acr-name>.azurecr.io/hanik-mcp-server:1.0.0'
   param containerPort = 8080
   ```

2. 인프라 배포:

   ```bash
   export CLIENT_APPLICATION_SECRET='...'
   ../deploy-bicep.sh --param-file ../main.local.bicepparam
   ```

3. `AcrPull` 권한 부여 후 앱 전환:

   ```bash
   ../deploy-app.sh \
     --param-file ../main.local.bicepparam \
     --registry-name <your-acr-name> \
     --image <your-acr-name>.azurecr.io/hanik-mcp-server:1.0.0
   ```

4. 배포 후 출력된 `containerAppUrl` 의 `/mcp` 엔드포인트를 Copilot Studio Agent 또는 Client Application의 MCP 연결 설정에 반영합니다.

## 파일 구조

```
app/
├── src/index.ts      # MCP 서버 (Streamable HTTP, test_hanik 도구)
├── Dockerfile        # 멀티스테이지 빌드 (node:20-alpine)
├── package.json
├── tsconfig.json
├── .dockerignore
└── .gitignore
```
