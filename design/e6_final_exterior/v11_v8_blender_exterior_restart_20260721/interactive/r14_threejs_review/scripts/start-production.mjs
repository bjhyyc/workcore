import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { createServer } from "node:http";
import path from "node:path";
import { Readable } from "node:stream";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const clientDir = path.join(root, "dist", "client");
const serverEntry = path.join(root, "dist", "server", "index.js");

function readArg(longName, shortName, fallback) {
  const args = process.argv.slice(2);
  const index = args.findIndex((arg) => arg === longName || arg === shortName);
  return index >= 0 && args[index + 1] ? args[index + 1] : fallback;
}

const port = Number(readArg("--port", "-p", process.env.PORT ?? "3000"));
const hostname = readArg("--hostname", "-H", "127.0.0.1");

const contentTypes = {
  ".css": "text/css; charset=utf-8",
  ".glb": "model/gltf-binary",
  ".html": "text/html; charset=utf-8",
  ".ico": "image/x-icon",
  ".js": "application/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".map": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
};

function resolveClientFile(pathname) {
  let decoded;
  try {
    decoded = decodeURIComponent(pathname);
  } catch {
    return null;
  }
  const relative = decoded.replace(/^\/+/, "");
  if (!relative || relative.startsWith(".vite/")) return null;
  const candidate = path.resolve(clientDir, relative);
  if (candidate !== clientDir && !candidate.startsWith(`${clientDir}${path.sep}`)) return null;
  return candidate;
}

async function getStaticResponse(request) {
  const file = resolveClientFile(new URL(request.url).pathname);
  if (!file) return null;
  try {
    const details = await stat(file);
    if (!details.isFile()) return null;
    const extension = path.extname(file).toLowerCase();
    const headers = new Headers({
      "Content-Type": contentTypes[extension] ?? "application/octet-stream",
      "Content-Length": String(details.size),
      "Cache-Control": extension === ".glb" ? "public, max-age=3600" : "public, max-age=31536000, immutable",
    });
    if (request.method === "HEAD") return new Response(null, { status: 200, headers });
    return new Response(Readable.toWeb(createReadStream(file)), { status: 200, headers });
  } catch {
    return null;
  }
}

const { default: worker } = await import(`${pathToFileURL(serverEntry).href}?t=${Date.now()}`);

async function sendNodeResponse(nodeResponse, webResponse, method) {
  const headers = Object.fromEntries(webResponse.headers.entries());
  nodeResponse.writeHead(webResponse.status, headers);
  if (method === "HEAD" || !webResponse.body) {
    nodeResponse.end();
    return;
  }
  Readable.fromWeb(webResponse.body).pipe(nodeResponse);
}

const server = createServer(async (req, res) => {
  try {
    const url = new URL(req.url ?? "/", `http://${req.headers.host ?? `${hostname}:${port}`}`);
    const requestInit = { method: req.method, headers: req.headers };
    if (req.method !== "GET" && req.method !== "HEAD") {
      requestInit.body = Readable.toWeb(req);
      requestInit.duplex = "half";
    }
    const request = new Request(url, requestInit);
    const staticResponse = await getStaticResponse(request);
    if (staticResponse) {
      await sendNodeResponse(res, staticResponse, req.method);
      return;
    }
    const response = await worker.fetch(
      request,
      {
        ASSETS: {
          fetch: async (assetRequest) =>
            (await getStaticResponse(assetRequest)) ?? new Response("Not found", { status: 404 }),
        },
      },
      { waitUntil() {}, passThroughOnException() {} },
    );
    await sendNodeResponse(res, response, req.method);
  } catch (error) {
    console.error(error);
    if (!res.headersSent) res.writeHead(500, { "Content-Type": "text/plain; charset=utf-8" });
    res.end("Internal Server Error");
  }
});

server.listen(port, hostname, () => {
  console.log(`WorkCore R14 production review running at http://${hostname}:${port}`);
});
