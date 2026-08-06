/* ============================================================
   EquipFlow shared auth cache
   All module pages use the same Google OAuth client + Sheets
   token flow (GIS token client). This helper caches the access
   token per-origin so navigating between modules doesn't
   re-prompt, and lets each page attempt silent sign-in on load.

   Usage from a module page (its existing auth code stays):
     - after receiving a token:   EQF.saveToken(resp, scope)
     - on load, before prompting: const t = EQF.cachedToken(scope)
     - on sign-out:               EQF.clearToken()
   A cached token is reused only if it has >2 min of life left
   and covers the scope the page needs.
   ============================================================ */
(function () {
  const KEY = "eqf_tok_v1";

  function now() { return Date.now(); }

  function saveToken(resp, scope) {
    try {
      const ttl = (Number(resp.expires_in) || 3600) * 1000;
      sessionStorage.setItem(KEY, JSON.stringify({
        access_token: resp.access_token,
        scope: scope || resp.scope || "",
        exp: now() + ttl - 120000   // refresh 2 min early
      }));
    } catch (e) {}
  }

  function cachedToken(neededScope) {
    try {
      const t = JSON.parse(sessionStorage.getItem(KEY) || "null");
      if (!t || !t.access_token) return null;
      if (t.exp <= now()) { sessionStorage.removeItem(KEY); return null; }
      // write scope satisfies readonly need
      if (neededScope && neededScope.includes("spreadsheets") &&
          !String(t.scope).includes("spreadsheets")) return null;
      if (neededScope && !neededScope.includes("readonly") &&
          neededScope.includes("auth/spreadsheets") &&
          String(t.scope).includes("readonly") &&
          !String(t.scope).match(/auth\/spreadsheets(\s|$|,)/)) return null;
      return t;
    } catch (e) { return null; }
  }

  function clearToken() {
    try { sessionStorage.removeItem(KEY); } catch (e) {}
  }

  window.EQF = { saveToken, cachedToken, clearToken };
})();
