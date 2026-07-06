export function renderDrmTestUiPage(config: { tenantId: string; clientId: string; scope: string }): string {
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
