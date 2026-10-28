// Copies contracts/fixtures into src/lib/api/fixtures for the development mock transport.
import { cpSync, mkdirSync, readdirSync, rmSync } from "node:fs";

const source = new URL("../../contracts/fixtures/", import.meta.url);
const target = new URL("../src/lib/api/fixtures/", import.meta.url);

rmSync(target, { recursive: true, force: true });
mkdirSync(target, { recursive: true });
const names = readdirSync(source).filter((name) => name.endsWith(".json"));
for (const name of names) cpSync(new URL(name, source), new URL(name, target));
console.log(`synced ${names.length} contract fixtures`);
