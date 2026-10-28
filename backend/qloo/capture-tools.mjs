// Captures the canonical `qloo mcp` tool surface into
// backend/app/integrations/qloo/verified/tools.json.
//
// Runs without a Qloo credential: QLOO_API_KEY is never passed, and QLOO_HOME points at a
// throwaway directory so no stored credential or user config can be read. Only
// listTools() and the local qloo_capabilities tool are called; no workflow runs, so
// nothing reaches Qloo. Usage (from backend/qloo): npm run capture-tools
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport, getDefaultEnvironment } from "@modelcontextprotocol/sdk/client/stdio.js";

const here = (relative) => fileURLToPath(new URL(relative, import.meta.url));
const harnessBin = here("./node_modules/@qloo/qloo-harness/dist/bin.js");
const outputPath = here("../app/integrations/qloo/verified/tools.json");
const versionOf = (pkg) => JSON.parse(readFileSync(here(`./node_modules/${pkg}/package.json`), "utf8")).version;

const qlooHome = mkdtempSync(join(tmpdir(), "nativeproof-qloo-capture-"));
const env = { ...getDefaultEnvironment(), QLOO_HOME: qlooHome, NO_COLOR: "1" };
delete env.QLOO_API_KEY;

const transport = new StdioClientTransport({ command: process.execPath, args: [harnessBin, "mcp"], env, stderr: "pipe" });
const client = new Client({ name: "nativeproof-tools-capture", version: "1.0.0" });
try {
  await client.connect(transport);
  const { tools } = await client.listTools();
  const capabilities = await client.callTool({ name: "qloo_capabilities", arguments: {} });
  const capture = {
    captured_on: new Date().toISOString().slice(0, 10),
    source: "qloo mcp (listTools + qloo_capabilities), no credential, no workflow calls",
    harness_package: "@qloo/qloo-harness",
    harness_version: versionOf("@qloo/qloo-harness"),
    mcp_sdk_version: versionOf("@modelcontextprotocol/sdk"),
    server: client.getServerVersion() ?? null,
    tools,
    capabilities: capabilities.structuredContent ?? JSON.parse(capabilities.content?.[0]?.text ?? "null"),
  };
  writeFileSync(outputPath, `${JSON.stringify(capture, null, 2)}\n`, "utf8");
  console.log(`Captured ${tools.length} tools to ${outputPath}`);
} finally {
  await client.close().catch(() => {});
  rmSync(qlooHome, { recursive: true, force: true });
}
