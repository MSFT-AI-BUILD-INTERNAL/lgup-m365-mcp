# Application Deployment Guide

`deploy-app.sh`를 사용하여 기존 Azure Container App에 latest 이미지를 배포하는 방법을 설명합니다.

## 개요

이 스크립트는 **Bicep 의존성 없이** 동작합니다. ACR과 Container App이 이미 존재하는 환경에서 이미지를 `latest` 태그로 빌드/푸시하고 Container App을 업데이트합니다.

```
┌─────────────┐      ┌─────────────┐      ┌──────────────────┐
│  소스 코드   │─────▶│  ACR 빌드   │─────▶│ Container App    │
│  (./app)    │      │  (latest)   │      │ 이미지 업데이트    │
└─────────────┘      └─────────────┘      └──────────────────┘
```

## 필수 값

| 값 | CLI 옵션 | 환경변수 | 설명 |
|----|----------|----------|------|
| Resource Group | `--resource-group` | `RESOURCE_GROUP_NAME` | 대상 리소스 그룹 |
| Container App | `--container-app` | `CONTAINER_APP_NAME` | Container App 이름 |
| ACR Name | `--registry-name` | `CONTAINER_REGISTRY_NAME` | Azure Container Registry 이름 |
| Image Name | `--image-name` | `CONTAINER_IMAGE_NAME` | 컨테이너 이미지 이름 (태그 없이; 항상 `:latest` 사용) |
| Managed Identity ID | `--managed-identity-id` | `MANAGED_IDENTITY_ID` | UAMI 리소스 ID (AcrPull 용) |

## 선택적 옵션

| CLI 옵션 | 환경변수 | 기본값 | 설명 |
|----------|----------|--------|------|
| `--build-context` | `BUILD_CONTEXT` | `./app` | Docker 빌드 컨텍스트 디렉토리 |
| `--skip-build` | `SKIP_BUILD=true` | `false` | ACR 빌드/푸시 건너뛰기 (ACR에 이미 latest 존재 시) |
| `--storage-account-url` | `AZURE_STORAGE_ACCOUNT_URL` | — | Azure Blob Storage 계정 URL (예: `https://<name>.blob.core.windows.net`) |
| `--storage-container` | `AZURE_STORAGE_CONTAINER` | `uploads` | Blob Storage 컨테이너 이름 |
| — | `SUBSCRIPTION_ID` | — | 설정 시 `az account set` 실행 |

## 배포 예시

### 빌드 후 배포

```bash
./deploy-app.sh \
  --resource-group rg-ms-azure-ax-prd \
  --container-app lgmcp-prd-mcp-api \
  --registry-name lgmcpprdacr \
  --image-name lgup-mcp-server \
  --managed-identity-id "/subscriptions/<subscription-id>/resourceGroups/rg-ms-azure-ax-prd/providers/Microsoft.ManagedIdentity/userAssignedIdentities/lgmcp-prd-uami" \
  --storage-account-url "https://lgmcpprdstorage.blob.core.windows.net"
```

### 이미 ACR에 latest 이미지가 있는 경우 (빌드 건너뛰기)

```bash
./deploy-app.sh \
  --resource-group rg-ms-azure-ax-prd \
  --container-app lgmcp-prd-mcp-api \
  --registry-name lgmcpprdacr \
  --image-name lgup-mcp-server \
  --managed-identity-id "/subscriptions/<subscription-id>/..." \
  --skip-build
```

### 환경변수 방식 (CI/CD 파이프라인)

```bash
export RESOURCE_GROUP_NAME="rg-ms-azure-ax-prd"
export CONTAINER_APP_NAME="ca-lgup-ax-demo"
export CONTAINER_REGISTRY_NAME="acrlgupdemo"
export CONTAINER_IMAGE_NAME="lgup-mcp-server"
export MANAGED_IDENTITY_ID="5d6d4023-84de-4129-bc72-62f257e3252f"
export SUBSCRIPTION_ID="2c73cb50-59c7-431f-a220-08423c087751"
export AZURE_STORAGE_ACCOUNT_URL="https://mslgupmcpdemostorage.blob.core.windows.net/"
export AZURE_STORAGE_CONTAINER="data"

./deploy-app.sh
```

## 스크립트 동작 흐름

```
1. 파라미터 수집 (CLI → 환경변수)
2. az acr build          → 이미지 빌드 및 ACR 푸시 (latest 태그)
3. az containerapp registry set → ACR 레지스트리 연결 (UAMI 인증)
4. az containerapp update       → 컨테이너 이미지 업데이트 + Storage 환경변수 설정
5. 헬스체크 (curl /health 또는 Azure 상태 폴링)
```

## Storage Account 설정

Storage 모듈(`/upload` 엔드포인트)을 사용하려면 Azure Blob Storage 계정이 필요합니다.

| 환경변수 | 용도 | 인증 방식 |
|----------|------|-----------|
| `AZURE_STORAGE_ACCOUNT_URL` | Storage 계정 URL | Managed Identity (운영) |
| `AZURE_STORAGE_CONNECTION_STRING` | 연결 문자열 | 키 기반 (로컬 개발) |
| `AZURE_STORAGE_CONTAINER` | Blob 컨테이너 이름 (기본: `uploads`) | — |

- **운영 환경**: `AZURE_STORAGE_ACCOUNT_URL`만 설정하면 `DefaultAzureCredential`(UAMI)로 인증합니다.
- **로컬 개발**: `AZURE_STORAGE_CONNECTION_STRING`을 설정하세요.
- 두 값 모두 미설정 시 `/upload` 엔드포인트는 `503 Service Unavailable`을 반환합니다.

### UAMI 역할 요구사항

Container App에 연결된 User-Assigned Managed Identity에 **Storage Blob Data Contributor** 역할을 부여해야 합니다:

```bash
az role assignment create \
  --assignee-object-id <UAMI_PRINCIPAL_ID> \
  --role "Storage Blob Data Contributor" \
  --scope "/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Storage/storageAccounts/<account>"
```

## 사전 조건

- **Azure CLI** (`az`) 설치 및 로그인 완료
- Container App에 연결된 **User-Assigned Managed Identity**에 ACR **AcrPull** 역할 부여 완료
- Container App이 이미 생성되어 있어야 함 (이 스크립트는 앱 업데이트만 수행)
- ACR이 동일 리소스 그룹에 존재해야 함
- (Storage 사용 시) UAMI에 **Storage Blob Data Contributor** 역할 부여 완료

## 사전 조건

- **Azure CLI** (`az`) 설치 및 로그인 완료
- **ACR**이 이미 생성되어 있어야 함
- **Container App**이 이미 생성되어 있어야 함 (이 스크립트는 앱 업데이트만 수행)
- Container App에 연결된 **User-Assigned Managed Identity**에 ACR **AcrPull** 역할 부여 완료

## 헬스체크

배포 후 자동으로 헬스체크를 수행합니다:

- `curl`이 사용 가능하고 Ingress URL이 있으면: `GET https://<app-url>/health`
- 그렇지 않으면: Azure 상태 (`runningStatus`, `provisioningState`) 폴링

최대 20회 × 5초 간격으로 재시도하며, 실패 시 트러블슈팅 명령어를 출력합니다.

## 트러블슈팅

헬스체크 실패 시 다음 명령어로 상태를 확인하세요:

```bash
# Container App 상태 확인
az containerapp show --name <app-name> --resource-group <rg> -o yaml

# 리비전 목록
az containerapp revision list --name <app-name> --resource-group <rg> -o table

# 시스템 로그
az containerapp logs show --name <app-name> --resource-group <rg> --type system --tail 200

# 앱 콘솔 로그
az containerapp logs show --name <app-name> --resource-group <rg> --type console --tail 200

# 활동 로그
az monitor activity-log list --resource-group <rg> --offset 1h --max-events 50 -o table
```
