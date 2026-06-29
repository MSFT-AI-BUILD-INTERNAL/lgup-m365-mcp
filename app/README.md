# hanik-mcp-server

`test hanik mcp ok` 메시지를 반환하는 최소 MCP 서버입니다. Azure Container Apps(상위 `main.bicep`)로 배포되며, M365 Copilot Studio Agent와 Client Application에서 호출할 수 있도록 컨테이너화되어 있습니다.

## 구성

- **전송 방식:** Streamable HTTP (`POST /mcp`) — Copilot Studio Agent 또는 원격 Client Application에서 호출 가능
- **포트:** `PORT` 환경변수 (기본 `8080`, Bicep의 `containerPort`와 일치)
- **도구(tool):** `test_hanik` — 입력 없이 `"test hanik mcp ok"` 텍스트를 반환
- **헬스 체크:** `GET /health` — Container Apps probe용

## 로컬 실행

```bash
npm install
npm run build
PORT=8080 npm start
```

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
