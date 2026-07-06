import { createHmac } from "node:crypto";
import { createRequire } from "node:module";
import express, { type Request, type Response } from "express";
import multer from "multer";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";

// Resolve the MSAL browser UMD bundle so the test UIs can load it locally
// (avoids depending on an external CDN that may be blocked on corporate networks).
const _require = createRequire(import.meta.url);
const MSAL_BROWSER_PATH = _require.resolve("@azure/msal-browser/lib/msal-browser.min.js");

const SERVER_NAME = "hanik-mcp-server";
const SERVER_VERSION = "1.0.0";

// Port is configurable so the Bicep-deployed Container App can inject containerPort (default 8080).
const PORT = Number(process.env.PORT ?? 8080);

const REQUIRED_SCOPE = "access_as_user";

function buildUiHtml(config: { tenantId: string; clientId: string; scope: string }): string {
  const defaultScope = `api://${config.clientId}/${config.scope}`;
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Entra Login + API Test</title>
  <style>
    :root {
      --bg-1: #0e1e2b;
      --bg-2: #153a52;
      --panel: rgba(255, 255, 255, 0.92);
      --ink: #0f172a;
      --muted: #475569;
      --accent: #0f766e;
      --accent-2: #0ea5e9;
      --ok: #166534;
      --bad: #b91c1c;
      --radius: 14px;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      color: var(--ink);
      font-family: "Segoe UI", "Noto Sans KR", "Apple SD Gothic Neo", sans-serif;
      background:
        radial-gradient(circle at 85% 15%, rgba(14, 165, 233, 0.32), transparent 32%),
        radial-gradient(circle at 15% 85%, rgba(15, 118, 110, 0.35), transparent 30%),
        linear-gradient(130deg, var(--bg-1), var(--bg-2));
      display: grid;
      place-items: center;
      padding: 24px;
    }
    .wrap {
      width: min(980px, 100%);
      background: var(--panel);
      border-radius: var(--radius);
      box-shadow: 0 22px 50px rgba(2, 12, 27, 0.35);
      overflow: hidden;
    }
    header {
      padding: 20px 24px;
      color: white;
      background: linear-gradient(90deg, #155e75, #0369a1);
    }
    h1 { margin: 0; font-size: 1.32rem; }
    p { margin: 8px 0 0; color: #dbeafe; }
    .content { padding: 18px 24px 24px; display: grid; gap: 18px; }
    .grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
    .card {
      border: 1px solid #e2e8f0;
      border-radius: 12px;
      padding: 14px;
      background: #fff;
    }
    label { display: block; margin-bottom: 6px; font-size: 0.88rem; color: var(--muted); }
    input, textarea, select {
      width: 100%;
      border: 1px solid #cbd5e1;
      border-radius: 10px;
      padding: 10px 11px;
      font: inherit;
    }
    textarea { min-height: 120px; resize: vertical; }
    .btns { display: flex; flex-wrap: wrap; gap: 10px; }
    button {
      border: 0;
      border-radius: 10px;
      padding: 10px 14px;
      font-weight: 600;
      cursor: pointer;
      color: #fff;
      background: var(--accent);
    }
    button.alt { background: var(--accent-2); }
    button.ghost { background: #64748b; }
    .status { font-size: 0.92rem; color: var(--muted); }
    .ok { color: var(--ok); font-weight: 600; }
    .bad { color: var(--bad); font-weight: 600; }
    pre {
      margin: 0;
      padding: 12px;
      border-radius: 10px;
      background: #0b1020;
      color: #e5e7eb;
      overflow: auto;
      font-size: 0.85rem;
      line-height: 1.38;
    }
    @media (max-width: 900px) { .grid { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <main class="wrap">
    <header>
      <h1>Entra ID Login + MCP API Test UI</h1>
      <p>로그인 후 Access Token을 받아 /mcp를 JSON-RPC 형식으로 호출합니다.</p>
    </header>
    <section class="content">
      <div class="grid">
        <article class="card">
          <h3>1) Entra 설정</h3>
          <label for="tenantId">Tenant ID</label>
          <input id="tenantId" value="${config.tenantId}" />
          <label for="clientId">Client ID (SPA App)</label>
          <input id="clientId" value="${config.clientId}" />
          <label for="scope">Scope</label>
          <input id="scope" value="${defaultScope}" />
          <div class="btns" style="margin-top:10px">
            <button id="loginBtn">Sign in</button>
            <button id="logoutBtn" class="ghost">Sign out</button>
            <button id="gotoDrmBtn" hidden>복호화 화면으로 이동 →</button>
          </div>
          <p class="status" id="authState">로그인 필요</p>
          <p class="status" id="userState"></p>
        </article>

        <article class="card">
          <h3>2) API 테스트</h3>
          <label for="endpoint">Endpoint</label>
          <input id="endpoint" value="/mcp" />
          <label for="method">Method</label>
          <select id="method">
            <option selected>POST</option>
            <option>GET</option>
          </select>
          <label for="payload">JSON Body</label>
          <textarea id="payload">{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"test_hanik","arguments":{}}}</textarea>
          <div class="btns" style="margin-top:10px">
            <button id="callBtn" class="alt">Call API</button>
            <button id="userBtn" class="ghost">Call get_current_user</button>
          </div>
        </article>
      </div>

      <article class="card">
        <h3>Access Token (preview)</h3>
        <pre id="tokenView">(token not acquired)</pre>
      </article>

      <article class="card">
        <h3>API Response</h3>
        <pre id="result">(no response yet)</pre>
      </article>
    </section>
  </main>

  <script src="/vendor/msal-browser.min.js"></script>
  <script>
    const authState = document.getElementById("authState");
    const userState = document.getElementById("userState");
    const resultEl = document.getElementById("result");
    const tokenView = document.getElementById("tokenView");
    const tenantIdEl = document.getElementById("tenantId");
    const clientIdEl = document.getElementById("clientId");
    const scopeEl = document.getElementById("scope");

    let msalApp;
    let account;
    let accessToken;

    function maskToken(token) {
      if (!token || token.length < 24) return "(token not acquired)";
      return token.slice(0, 20) + " ... " + token.slice(-20);
    }

    function decodeJwt(token) {
      try {
        const parts = token.split(".");
        if (parts.length < 2) return null;
        const b64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
        const json = decodeURIComponent(
          atob(b64)
            .split("")
            .map((c) => "%" + ("00" + c.charCodeAt(0).toString(16)).slice(-2))
            .join("")
        );
        return JSON.parse(json);
      } catch {
        return null;
      }
    }

    function buildLoginInfo(loginResp, tokenResp) {
      const acct = (tokenResp && tokenResp.account) || (loginResp && loginResp.account) || null;
      return {
        account: acct
          ? {
              username: acct.username,
              name: acct.name,
              localAccountId: acct.localAccountId,
              homeAccountId: acct.homeAccountId,
              tenantId: acct.tenantId,
              environment: acct.environment,
            }
          : null,
        idTokenClaims: acct ? acct.idTokenClaims : null,
        accessTokenClaims: tokenResp ? decodeJwt(tokenResp.accessToken) : null,
        scopes: tokenResp ? tokenResp.scopes : null,
        expiresOn: tokenResp ? tokenResp.expiresOn : null,
        accessToken: tokenResp ? tokenResp.accessToken : null,
      };
    }

    function setStatus(text, ok) {
      authState.textContent = text;
      authState.className = ok ? "status ok" : "status bad";
    }

    function getConfig() {
      return {
        tenantId: tenantIdEl.value.trim(),
        clientId: clientIdEl.value.trim(),
        scope: scopeEl.value.trim(),
      };
    }

    function ensureMsal() {
      const cfg = getConfig();
      if (!cfg.tenantId || !cfg.clientId || !cfg.scope) {
        throw new Error("tenantId/clientId/scope 를 입력해 주세요.");
      }
      msalApp = new msal.PublicClientApplication({
        auth: {
          clientId: cfg.clientId,
          authority: "https://login.microsoftonline.com/" + cfg.tenantId,
          redirectUri: window.location.origin + window.location.pathname,
        },
        cache: {
          cacheLocation: "sessionStorage",
          storeAuthStateInCookie: false,
        },
      });
      return cfg;
    }

    async function signIn() {
      try {
        const cfg = ensureMsal();
        const loginResp = await msalApp.loginPopup({ scopes: ["openid", "profile", "email", cfg.scope] });
        account = loginResp.account;
        const tokenResp = await msalApp.acquireTokenSilent({
          account,
          scopes: [cfg.scope],
        }).catch(() => msalApp.acquireTokenPopup({ scopes: [cfg.scope] }));
        accessToken = tokenResp.accessToken;
        setStatus("인증 성공", true);
        userState.textContent = account ? String(account.username) : "";
        tokenView.textContent = maskToken(accessToken);
        resultEl.textContent = JSON.stringify(buildLoginInfo(loginResp, tokenResp), null, 2);
        document.getElementById("gotoDrmBtn").hidden = false;
      } catch (error) {
        setStatus("인증 실패", false);
        resultEl.textContent = String(error && error.message ? error.message : error);
      }
    }

    async function signOut() {
      if (msalApp && account) {
        await msalApp.logoutPopup({ account });
      }
      account = null;
      accessToken = null;
      setStatus("로그아웃됨", false);
      userState.textContent = "";
      tokenView.textContent = "(token not acquired)";
      document.getElementById("gotoDrmBtn").hidden = true;
    }

    async function callApi() {
      if (!accessToken) {
        setStatus("API 호출 전 로그인 필요", false);
        return;
      }

      const endpoint = document.getElementById("endpoint").value.trim() || "/mcp";
      const method = document.getElementById("method").value;
      const payloadText = document.getElementById("payload").value.trim();

      let body;
      if (method === "POST") {
        body = payloadText ? JSON.parse(payloadText) : undefined;
      }

      const response = await fetch(endpoint, {
        method,
        headers: {
          "Content-Type": "application/json",
          "Accept": "application/json, text/event-stream",
          "Authorization": "Bearer " + accessToken,
        },
        body: method === "POST" ? JSON.stringify(body) : undefined,
      });

      const text = await response.text();
      let parsed = text;
      try { parsed = JSON.parse(text); } catch {}
      resultEl.textContent = JSON.stringify({
        status: response.status,
        statusText: response.statusText,
        body: parsed,
      }, null, 2);
    }

    function callCurrentUser() {
      document.getElementById("method").value = "POST";
      document.getElementById("endpoint").value = "/mcp";
      document.getElementById("payload").value = JSON.stringify({
        jsonrpc: "2.0",
        id: 2,
        method: "tools/call",
        params: { name: "get_current_user", arguments: {} },
      }, null, 2);
      return callApi();
    }

    document.getElementById("loginBtn").addEventListener("click", signIn);
    document.getElementById("logoutBtn").addEventListener("click", signOut);
    document.getElementById("gotoDrmBtn").addEventListener("click", () => {
      window.location.href = "/drm-ui";
    });
    document.getElementById("callBtn").addEventListener("click", () => {
      callApi().catch((err) => {
        setStatus("API 호출 실패", false);
        resultEl.textContent = String(err && err.message ? err.message : err);
      });
    });
    document.getElementById("userBtn").addEventListener("click", () => {
      callCurrentUser().catch((err) => {
        setStatus("API 호출 실패", false);
        resultEl.textContent = String(err && err.message ? err.message : err);
      });
    });
  </script>
</body>
</html>`;
}

/**
 * Decode the payload (claims) of a JWT without verifying its signature.
 * NOTE: This only reads claims for display. For trust decisions the token
 * signature/audience/issuer MUST be validated (e.g. via Entra ID JWKS).
 */
function decodeJwtClaims(token: string): Record<string, unknown> | null {
  const parts = token.split(".");
  if (parts.length < 2) {
    return null;
  }
  try {
    const payload = Buffer.from(parts[1], "base64url").toString("utf8");
    return JSON.parse(payload) as Record<string, unknown>;
  } catch {
    return null;
  }
}

/**
 * Resolve the calling user's identity from the incoming request.
 * Supports two common patterns when fronted by Copilot Studio / Azure auth:
 *  1. Azure Container Apps "Easy Auth" injected headers (x-ms-client-principal*).
 *  2. A forwarded Entra ID bearer token in the Authorization header.
 */
function resolveCurrentUser(req: Request): Record<string, unknown> {
  const headers = req.headers;

  // 1) Easy Auth simple headers.
  const principalName = headers["x-ms-client-principal-name"];
  const principalId = headers["x-ms-client-principal-id"];
  const principalIdp = headers["x-ms-client-principal-idp"];

  // 1b) Easy Auth full base64-encoded principal (claims array).
  let easyAuthClaims: Record<string, unknown> | null = null;
  const encodedPrincipal = headers["x-ms-client-principal"];
  if (typeof encodedPrincipal === "string") {
    try {
      easyAuthClaims = JSON.parse(
        Buffer.from(encodedPrincipal, "base64").toString("utf8")
      ) as Record<string, unknown>;
    } catch {
      easyAuthClaims = null;
    }
  }

  // 2) Bearer token claims.
  let tokenClaims: Record<string, unknown> | null = null;
  const authHeader = headers["authorization"];
  if (typeof authHeader === "string" && authHeader.toLowerCase().startsWith("bearer ")) {
    tokenClaims = decodeJwtClaims(authHeader.slice(7).trim());
  }

  const claims = tokenClaims ?? {};
  const displayName =
    (typeof principalName === "string" ? principalName : undefined) ??
    (claims.name as string | undefined) ??
    (claims.preferred_username as string | undefined) ??
    (claims.upn as string | undefined);
  const userId =
    (typeof principalId === "string" ? principalId : undefined) ??
    (claims.oid as string | undefined) ??
    (claims.sub as string | undefined);

  const authenticated = Boolean(displayName || userId || easyAuthClaims);

  return {
    authenticated,
    displayName: displayName ?? null,
    userPrincipalName:
      (claims.preferred_username as string | undefined) ??
      (claims.upn as string | undefined) ??
      (typeof principalName === "string" ? principalName : null),
    email: (claims.email as string | undefined) ?? null,
    objectId: userId ?? null,
    tenantId: (claims.tid as string | undefined) ?? null,
    identityProvider: typeof principalIdp === "string" ? principalIdp : null,
    scopes:
      (claims.scp as string | undefined) ??
      (claims.roles as string[] | undefined) ??
      null,
  };
}

/**
 * Build a fresh MCP server instance per request (stateless Streamable HTTP).
 * Stateless mode keeps the server simple and horizontally scalable on Azure Container Apps.
 */
function createMcpServer(req: Request): McpServer {
  const server = new McpServer({
    name: SERVER_NAME,
    version: SERVER_VERSION,
  });

  // Single test tool: always replies with "test hanik mcp ok".
  server.registerTool(
    "test_hanik",
    {
      title: "Test Hanik",
      description: "A connectivity test tool that returns a fixed confirmation message.",
      inputSchema: {},
    },
    async () => ({
      content: [
        {
          type: "text",
          text: "test hanik mcp ok",
        },
      ],
    })
  );

  // Returns information about the user that is calling this MCP server
  // (for example, the signed-in Copilot Studio user, when identity is forwarded).
  server.registerTool(
    "get_current_user",
    {
      title: "Get Current User",
      description:
        "Returns information about the connected user (Copilot Studio caller) derived from the forwarded identity headers or bearer token.",
      inputSchema: {},
    },
    async () => {
      const user = resolveCurrentUser(req);
      const text = user.authenticated
        ? JSON.stringify(user, null, 2)
        : "No user identity was forwarded to the MCP server. The endpoint is currently unauthenticated, so enable authentication on the Container App / APIM and configure Copilot Studio to forward the user token to receive caller details.";
      return {
        content: [
          {
            type: "text",
            text,
          },
        ],
      };
    }
  );

  return server;
}

function buildDrmUiHtml(config: { tenantId: string; clientId: string; scope: string }): string {
  const defaultScope = `api://${config.clientId}/${config.scope}`;
  return `<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>DRM Decrypt Test (Entra Login)</title>
  <style>
    :root {
      --bg-1: #0e1e2b;
      --bg-2: #153a52;
      --panel: rgba(255, 255, 255, 0.95);
      --ink: #0f172a;
      --muted: #475569;
      --accent: #0f766e;
      --accent-2: #0ea5e9;
      --ok: #166534;
      --bad: #b91c1c;
      --radius: 14px;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      color: var(--ink);
      font-family: "Segoe UI", "Noto Sans KR", "Apple SD Gothic Neo", sans-serif;
      background:
        radial-gradient(circle at 85% 15%, rgba(14, 165, 233, 0.32), transparent 32%),
        radial-gradient(circle at 15% 85%, rgba(15, 118, 110, 0.35), transparent 30%),
        linear-gradient(130deg, var(--bg-1), var(--bg-2));
      display: grid;
      place-items: center;
      padding: 24px;
    }
    .wrap { width: min(760px, 100%); }
    .card {
      background: var(--panel);
      border-radius: var(--radius);
      box-shadow: 0 22px 50px rgba(2, 12, 27, 0.35);
      overflow: hidden;
    }
    header { padding: 20px 24px; color: #fff; background: linear-gradient(90deg, #155e75, #0369a1); }
    h1 { margin: 0; font-size: 1.28rem; }
    header p { margin: 8px 0 0; color: #dbeafe; font-size: 0.92rem; }
    .body { padding: 22px 24px; display: grid; gap: 16px; }
    label { display: block; margin-bottom: 6px; font-size: 0.88rem; color: var(--muted); }
    input, select {
      width: 100%;
      border: 1px solid #cbd5e1;
      border-radius: 10px;
      padding: 10px 11px;
      font: inherit;
      background: #fff;
    }
    .btns { display: flex; flex-wrap: wrap; gap: 10px; }
    button {
      border: 0;
      border-radius: 10px;
      padding: 11px 16px;
      font-weight: 600;
      cursor: pointer;
      color: #fff;
      background: var(--accent);
    }
    button.alt { background: var(--accent-2); }
    button.ghost { background: #64748b; }
    button:disabled { opacity: 0.5; cursor: not-allowed; }
    .status { font-size: 0.92rem; color: var(--muted); margin: 0; }
    .ok { color: var(--ok); font-weight: 600; }
    .bad { color: var(--bad); font-weight: 600; }
    pre {
      margin: 0;
      padding: 12px;
      border-radius: 10px;
      background: #0b1020;
      color: #e5e7eb;
      overflow: auto;
      font-size: 0.85rem;
      line-height: 1.4;
      max-height: 260px;
    }
    /* Login gate overlay: shown first, blocks the app until authenticated */
    #gate {
      position: fixed;
      inset: 0;
      display: grid;
      place-items: center;
      padding: 24px;
      background: rgba(4, 15, 28, 0.72);
      backdrop-filter: blur(3px);
      z-index: 10;
    }
    #gate .card { width: min(420px, 100%); }
    #app[hidden] { display: none; }
    .hidden { display: none !important; }
    .config { border: 1px solid #e2e8f0; border-radius: 12px; padding: 14px; background: #fff; }
    .config summary { cursor: pointer; font-weight: 600; color: var(--muted); }
    .config .grid { display: grid; gap: 10px; margin-top: 12px; }
  </style>
</head>
<body>
  <!-- Login gate: appears first -->
  <div id="gate">
    <div class="card">
      <header>
        <h1>Entra ID 로그인</h1>
        <p>DRM 복호화 테스트를 사용하려면 먼저 로그인하세요.</p>
      </header>
      <div class="body">
        <details class="config">
          <summary>Entra 설정</summary>
          <div class="grid">
            <div>
              <label for="tenantId">Tenant ID</label>
              <input id="tenantId" value="${config.tenantId}" />
            </div>
            <div>
              <label for="clientId">Client ID (SPA App)</label>
              <input id="clientId" value="${config.clientId}" />
            </div>
            <div>
              <label for="scope">Scope</label>
              <input id="scope" value="${defaultScope}" />
            </div>
          </div>
        </details>
        <div class="btns">
          <button id="loginBtn">Sign in with Entra ID</button>
        </div>
        <p class="status" id="gateState">로그인 필요</p>
      </div>
    </div>
  </div>

  <!-- Main app: hidden until login succeeds -->
  <main class="wrap">
    <div class="card" id="app" hidden>
      <header>
        <h1>DRM / MIP Decrypt Test</h1>
        <p id="who"></p>
      </header>
      <div class="body">
        <div>
          <label for="file">복호화할 파일 선택</label>
          <input id="file" type="file" />
        </div>
        <div class="btns">
          <button id="decryptBtn" class="alt">Decrypt 호출</button>
          <button id="logoutBtn" class="ghost">Sign out</button>
        </div>
        <p class="status" id="callState"></p>
        <div>
          <label>결과</label>
          <pre id="result">(no response yet)</pre>
        </div>
      </div>
    </div>
  </main>

  <script src="/vendor/msal-browser.min.js"></script>
  <script>
    const gate = document.getElementById("gate");
    const appEl = document.getElementById("app");
    const gateState = document.getElementById("gateState");
    const callState = document.getElementById("callState");
    const who = document.getElementById("who");
    const resultEl = document.getElementById("result");
    const tenantIdEl = document.getElementById("tenantId");
    const clientIdEl = document.getElementById("clientId");
    const scopeEl = document.getElementById("scope");

    let msalApp;
    let account;
    let accessToken;

    function setGate(text, ok) {
      gateState.textContent = text;
      gateState.className = ok ? "status ok" : "status bad";
    }
    function setCall(text, ok) {
      callState.textContent = text;
      callState.className = ok ? "status ok" : "status bad";
    }

    function getConfig() {
      return {
        tenantId: tenantIdEl.value.trim(),
        clientId: clientIdEl.value.trim(),
        scope: scopeEl.value.trim(),
      };
    }

    function ensureMsal() {
      const cfg = getConfig();
      if (!cfg.tenantId || !cfg.clientId || !cfg.scope) {
        throw new Error("tenantId/clientId/scope 를 입력해 주세요.");
      }
      msalApp = new msal.PublicClientApplication({
        auth: {
          clientId: cfg.clientId,
          authority: "https://login.microsoftonline.com/" + cfg.tenantId,
          redirectUri: window.location.origin + window.location.pathname,
        },
        cache: { cacheLocation: "sessionStorage", storeAuthStateInCookie: false },
      });
      return cfg;
    }

    function showApp() {
      gate.classList.add("hidden");
      appEl.hidden = false;
      who.textContent = account ? "Signed in: " + (account.name || account.username) : "";
    }

    function decodeJwt(token) {
      try {
        const parts = token.split(".");
        if (parts.length < 2) return null;
        const b64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
        const json = decodeURIComponent(
          atob(b64)
            .split("")
            .map((c) => "%" + ("00" + c.charCodeAt(0).toString(16)).slice(-2))
            .join("")
        );
        return JSON.parse(json);
      } catch {
        return null;
      }
    }

    function buildLoginInfo(loginResp, tokenResp) {
      const acct = (tokenResp && tokenResp.account) || (loginResp && loginResp.account) || null;
      return {
        account: acct
          ? {
              username: acct.username,
              name: acct.name,
              localAccountId: acct.localAccountId,
              homeAccountId: acct.homeAccountId,
              tenantId: acct.tenantId,
              environment: acct.environment,
            }
          : null,
        idTokenClaims: acct ? acct.idTokenClaims : null,
        accessTokenClaims: tokenResp ? decodeJwt(tokenResp.accessToken) : null,
        scopes: tokenResp ? tokenResp.scopes : null,
        expiresOn: tokenResp ? tokenResp.expiresOn : null,
        accessToken: tokenResp ? tokenResp.accessToken : null,
      };
    }

    async function signIn() {
      try {
        const cfg = ensureMsal();
        const loginResp = await msalApp.loginPopup({ scopes: ["openid", "profile", "email", cfg.scope] });
        account = loginResp.account;
        const tokenResp = await msalApp
          .acquireTokenSilent({ account, scopes: [cfg.scope] })
          .catch(() => msalApp.acquireTokenPopup({ scopes: [cfg.scope] }));
        accessToken = tokenResp.accessToken;
        setGate("인증 성공", true);
        showApp();
        setCall("로그인 반환값을 아래에 표시했습니다.", true);
        resultEl.textContent = JSON.stringify(buildLoginInfo(loginResp, tokenResp), null, 2);
      } catch (error) {
        setGate("인증 실패: " + (error && error.message ? error.message : error), false);
      }
    }

    async function signOut() {
      if (msalApp && account) {
        await msalApp.logoutPopup({ account });
      }
      account = null;
      accessToken = null;
      appEl.hidden = true;
      gate.classList.remove("hidden");
      setGate("로그아웃됨", false);
    }

    async function decrypt() {
      if (!accessToken) {
        setCall("로그인이 필요합니다.", false);
        return;
      }
      const fileInput = document.getElementById("file");
      if (!fileInput.files || fileInput.files.length === 0) {
        setCall("파일을 선택하세요.", false);
        return;
      }
      setCall("호출 중...", true);
      resultEl.textContent = "(calling /drm/decrypt ...)";

      const form = new FormData();
      form.append("file", fileInput.files[0]);

      const response = await fetch("/drm/decrypt", {
        method: "POST",
        headers: { "Authorization": "Bearer " + accessToken },
        body: form,
      });

      const contentType = response.headers.get("content-type") || "";
      if (response.ok && !contentType.includes("application/json")) {
        // Binary result: trigger download.
        const disposition = response.headers.get("content-disposition") || "";
        const match = /filename\\*?=(?:UTF-8''|")?([^";]+)/i.exec(disposition);
        const fileName = match ? decodeURIComponent(match[1]) : "decrypted.bin";
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = fileName;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
        setCall("복호화 성공 — 파일 다운로드됨: " + fileName, true);
        resultEl.textContent = JSON.stringify({
          status: response.status,
          contentType,
          downloadedAs: fileName,
        }, null, 2);
        return;
      }

      const text = await response.text();
      let parsed = text;
      try { parsed = JSON.parse(text); } catch {}
      setCall(response.ok ? "응답 수신" : "호출 실패 (" + response.status + ")", response.ok);
      resultEl.textContent = JSON.stringify({
        status: response.status,
        statusText: response.statusText,
        body: parsed,
      }, null, 2);
    }

    document.getElementById("loginBtn").addEventListener("click", signIn);
    document.getElementById("logoutBtn").addEventListener("click", signOut);
    document.getElementById("decryptBtn").addEventListener("click", () => {
      decrypt().catch((err) => {
        setCall("호출 실패: " + (err && err.message ? err.message : err), false);
      });
    });
  </script>
</body>
</html>`;
}

const app = express();
app.use(express.json());

// Serve the MSAL browser library locally so the login UIs work without an external CDN.
app.get("/vendor/msal-browser.min.js", (_req: Request, res: Response) => {
  res.setHeader("Content-Type", "application/javascript; charset=utf-8");
  res.sendFile(MSAL_BROWSER_PATH);
});

const drmUpload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: 50 * 1024 * 1024 },
});

app.get("/auth-ui/config", (_req: Request, res: Response) => {
  const authClientId = process.env.AUTH_CLIENT_ID ?? "";
  const authTenantId = process.env.AUTH_TENANT_ID ?? "";
  res.json({
    tenantId: authTenantId,
    clientId: authClientId,
    scope: authClientId ? `api://${authClientId}/${REQUIRED_SCOPE}` : "",
  });
});

app.get("/auth-ui", (_req: Request, res: Response) => {
  const authClientId = process.env.AUTH_CLIENT_ID ?? "";
  const authTenantId = process.env.AUTH_TENANT_ID ?? "";

  if (!authClientId || !authTenantId) {
    res.status(503).send(
      "AUTH_CLIENT_ID / AUTH_TENANT_ID environment variables are required for Entra ID test UI."
    );
    return;
  }

  res.setHeader("Content-Type", "text/html; charset=utf-8");
  res.status(200).send(
    buildUiHtml({ tenantId: authTenantId, clientId: authClientId, scope: REQUIRED_SCOPE })
  );
});

// DRM / MIP decrypt test UI (Entra login gate shown first).
app.get("/drm-ui", (_req: Request, res: Response) => {
  const authClientId = process.env.AUTH_CLIENT_ID ?? "";
  const authTenantId = process.env.AUTH_TENANT_ID ?? "";

  if (!authClientId || !authTenantId) {
    res.status(503).send(
      "AUTH_CLIENT_ID / AUTH_TENANT_ID environment variables are required for the DRM test UI."
    );
    return;
  }

  res.setHeader("Content-Type", "text/html; charset=utf-8");
  res.status(200).send(
    buildDrmUiHtml({ tenantId: authTenantId, clientId: authClientId, scope: REQUIRED_SCOPE })
  );
});

/**
 * Server-side proxy for the DRM/MIP decrypt API.
 * Secrets (client id, key id, secret key, user identity, host) are read from
 * environment variables so they are never exposed to the browser. The HMAC
 * signature is computed here and the uploaded file is forwarded to the DRM API.
 * Requires a valid Entra bearer token with the delegated scope.
 */
app.post("/drm/decrypt", drmUpload.single("file"), async (req: Request, res: Response) => {
  if (!requireScope(req, res)) return;

  const host = process.env.DRM_HOST ?? "seulgiapi.lguplus.co.kr";
  const clientId = process.env.DRM_CLIENT_ID;
  const keyId = process.env.DRM_KEY_ID;
  const secretKey = process.env.DRM_SECRET_KEY;
  const email = process.env.DRM_USER_EMAIL;
  const loginId = process.env.DRM_USER_LOGINID;

  if (!clientId || !keyId || !secretKey || !email || !loginId) {
    res.status(503).json({
      error:
        "DRM proxy is not configured. Set DRM_CLIENT_ID, DRM_KEY_ID, DRM_SECRET_KEY, DRM_USER_EMAIL and DRM_USER_LOGINID environment variables.",
    });
    return;
  }

  const file = (req as Request & { file?: { buffer: Buffer; originalname: string; mimetype: string } }).file;
  if (!file) {
    res.status(400).json({ error: "No file uploaded. Attach a 'file' field." });
    return;
  }

  const timestamp = Math.floor(Date.now() / 1000).toString();
  const signingString = `${host};${clientId};${keyId};${timestamp};${email};${loginId}`;
  const hmac = createHmac("sha256", secretKey).update(signingString).digest("base64");

  const authorization = `SEULGI-HMAC-SHA256-V1 SigHeaders=host;x-client-id;x-key-id;x-timestamp,x-user-email,Signature=${hmac}`;

  try {
    const form = new FormData();
    const blob = new Blob([new Uint8Array(file.buffer)], {
      type: file.mimetype || "application/octet-stream",
    });
    form.append("file", blob, file.originalname);

    const upstream = await fetch(`https://${host}/v1/mip/decrypt`, {
      method: "POST",
      headers: {
        "x-client-id": clientId,
        "x-key-id": keyId,
        "x-timestamp": timestamp,
        "x-user-email": email,
        "x-user-loginId": loginId,
        Authorization: authorization,
      },
      body: form,
    });

    const upstreamContentType = upstream.headers.get("content-type") ?? "application/octet-stream";
    const upstreamDisposition = upstream.headers.get("content-disposition");

    if (!upstream.ok) {
      const errorText = await upstream.text();
      res.status(upstream.status).json({
        error: "DRM API returned an error.",
        status: upstream.status,
        body: errorText,
      });
      return;
    }

    const arrayBuffer = await upstream.arrayBuffer();
    res.status(200);
    res.setHeader("Content-Type", upstreamContentType);
    res.setHeader(
      "Content-Disposition",
      upstreamDisposition ?? `attachment; filename="decrypted-${file.originalname}"`
    );
    res.send(Buffer.from(arrayBuffer));
  } catch (error) {
    console.error("DRM decrypt proxy error:", error);
    res.status(502).json({
      error: "Failed to reach the DRM API.",
      detail: error instanceof Error ? error.message : String(error),
    });
  }
});

// Liveness/readiness probe endpoint for Azure Container Apps.
app.get("/health", (_req: Request, res: Response) => {
  res.status(200).json({ status: "ok", server: SERVER_NAME, version: SERVER_VERSION });
});

// RFC 9728 — OAuth Protected Resource Metadata.
// Advertises this server's auth requirements so OAuth-aware MCP clients can auto-discover them.
app.get("/.well-known/oauth-protected-resource", (req: Request, res: Response) => {
  const authClientId = process.env.AUTH_CLIENT_ID;
  const authTenantId = process.env.AUTH_TENANT_ID;

  if (!authClientId || !authTenantId) {
    res.status(503).json({
      error: "OAuth metadata not configured. AUTH_CLIENT_ID and AUTH_TENANT_ID environment variables are required.",
    });
    return;
  }

  // Point to our own server as the authorization server metadata host.
  const baseUrl = `${req.protocol}://${req.get("host")}`;

  res.json({
    resource: `api://${authClientId}`,
    authorization_servers: [baseUrl],
    scopes_supported: ["access_as_user"],
    bearer_methods_supported: ["header"],
  });
});

// RFC 8414 — OAuth Authorization Server Metadata.
// Advertises Entra ID endpoints so OAuth clients can discover token/authorize URLs.
app.get("/.well-known/oauth-authorization-server", (req: Request, res: Response) => {
  const authClientId = process.env.AUTH_CLIENT_ID;
  const authTenantId = process.env.AUTH_TENANT_ID;

  if (!authClientId || !authTenantId) {
    res.status(503).json({
      error: "OAuth metadata not configured. AUTH_CLIENT_ID and AUTH_TENANT_ID environment variables are required.",
    });
    return;
  }

  const baseUrl = `${req.protocol}://${req.get("host")}`;
  const entraBase = `https://login.microsoftonline.com/${authTenantId}/v2.0`;

  res.json({
    issuer: entraBase,
    authorization_endpoint: `https://login.microsoftonline.com/${authTenantId}/oauth2/v2.0/authorize`,
    token_endpoint: `https://login.microsoftonline.com/${authTenantId}/oauth2/v2.0/token`,
    jwks_uri: `https://login.microsoftonline.com/${authTenantId}/discovery/v2.0/keys`,
    scopes_supported: ["openid", "profile", "email", "offline_access", `api://${authClientId}/access_as_user`],
    response_types_supported: ["code"],
    grant_types_supported: ["authorization_code", "client_credentials"],
    token_endpoint_auth_methods_supported: ["client_secret_post", "client_secret_basic"],
    code_challenge_methods_supported: ["S256"],
  });
});

// Streamable HTTP MCP endpoint (stateless: a new server + transport per request).
/**
 * Validates that the incoming request carries a token with the required scope.
 * APIM performs primary JWT signature/audience/issuer validation; this is a
 * defence-in-depth check ensuring the correct delegated permission is present.
 */
function requireScope(req: Request, res: Response): boolean {
  const authHeader = req.headers["authorization"];
  if (typeof authHeader !== "string" || !authHeader.toLowerCase().startsWith("bearer ")) {
    const authClientId = process.env.AUTH_CLIENT_ID ?? "";
    const authTenantId = process.env.AUTH_TENANT_ID ?? "";
    res.setHeader(
      "WWW-Authenticate",
      `Bearer realm="api://${authClientId}", authorization_uri="https://login.microsoftonline.com/${authTenantId}/oauth2/v2.0/authorize"`
    );
    res.status(401).json({
      jsonrpc: "2.0",
      error: { code: -32000, message: "Unauthorized. Bearer token required." },
      id: null,
    });
    return false;
  }

  const claims = decodeJwtClaims(authHeader.slice(7).trim());
  if (claims) {
    const scp = typeof claims.scp === "string" ? claims.scp.split(" ") : [];
    const roles = Array.isArray(claims.roles) ? (claims.roles as string[]) : [];
    const allScopes = [...scp, ...roles];
    if (!allScopes.includes(REQUIRED_SCOPE)) {
      res.status(403).json({
        jsonrpc: "2.0",
        error: {
          code: -32000,
          message: `Forbidden. Token must include the '${REQUIRED_SCOPE}' scope.`,
        },
        id: null,
      });
      return false;
    }
  }

  return true;
}

// Streamable HTTP MCP endpoint (stateless: a new server + transport per request).
app.post("/mcp", async (req: Request, res: Response) => {
  if (!requireScope(req, res)) return;

  const server = createMcpServer(req);
  const transport = new StreamableHTTPServerTransport({
    sessionIdGenerator: undefined,
  });

  res.on("close", () => {
    void transport.close();
    void server.close();
  });

  try {
    await server.connect(transport);
    await transport.handleRequest(req, res, req.body);
  } catch (error) {
    console.error("Error handling MCP request:", error);
    if (!res.headersSent) {
      res.status(500).json({
        jsonrpc: "2.0",
        error: { code: -32603, message: "Internal server error" },
        id: null,
      });
    }
  }
});

// Stateless mode does not support server-initiated streams or session termination.
const methodNotAllowed = (_req: Request, res: Response) => {
  res.status(405).json({
    jsonrpc: "2.0",
    error: { code: -32000, message: "Method not allowed." },
    id: null,
  });
};
app.get("/mcp", methodNotAllowed);
app.delete("/mcp", methodNotAllowed);

app.listen(PORT, () => {
  console.log(`${SERVER_NAME} v${SERVER_VERSION} listening on port ${PORT} (POST /mcp)`);
});
