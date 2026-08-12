import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request("http://localhost/", { headers: { accept: "text/html" } }),
    {
      ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) },
    },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("server-renders the ContaMind sign-in experience", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>ContaMind \| Salud contable<\/title>/i);
  assert.match(html, /CONTAMIND · SALUD CONTABLE/);
  assert.match(html, /Ingresa a tu espacio/);
  assert.match(html, /Correo electrónico/);
  assert.match(html, /Contraseña/);
  assert.doesNotMatch(html, /react-loading-skeleton|Building your site|codex-preview/i);
});

test("keeps the health-agent contract and privacy boundary in the client", async () => {
  const [page, api, layout, component, environment] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/health-agent/api.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/health-agent/HealthAgentApp.tsx", import.meta.url), "utf8"),
    readFile(new URL("../.env.example", import.meta.url), "utf8"),
  ]);

  assert.match(page, /HealthAgentApp/);
  assert.match(api, /\/auth\/login/);
  assert.match(api, /\/companies\/mine/);
  assert.match(api, /\/companies\/\$\{companyId\}\/agents\/accounting-health\/chat/);
  assert.match(api, /Authorization: `Bearer \$\{token\}`/);
  assert.match(environment, /VITE_API_BASE_URL=http:\/\/localhost:8000\/api\/v1/);
  assert.match(layout, /title: "ContaMind \| Salud contable"/);
  assert.match(layout, /images: \["\/og\.png"\]/);
  assert.match(component, /No incluyas NIT, correos, documentos ni\s+credenciales/);
  assert.match(component, /No tienes empresas disponibles/);
  assert.match(component, /Esta empresa está desactivada/);
  assert.doesNotMatch(component, /localStorage|sessionStorage/);

  await access(new URL("../public/og.png", import.meta.url));
});
