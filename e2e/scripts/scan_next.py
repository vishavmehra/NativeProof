"""Scan a Next.js build output for secrets. Prints counts and masked context only, never a secret value.

usage: python -I scan_next.py <.next dir> <frontend .env.local> <backend .env>
"""
import re
import sys
from pathlib import Path

next_dir, frontend_env, backend_env = map(Path, sys.argv[1:4])


def env_values(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"')
    return values


fe, be = env_values(frontend_env), env_values(backend_env)
publishable = fe.get("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", "")
real_secrets = {f"backend .env {k}": v for k, v in be.items() if len(v) >= 8 and re.search(r"KEY|SECRET|PASSWORD|DATABASE_URL|TOKEN", k)}
dummies = {"dummy NEBIUS_API_KEY": "SCANDUMMYnebius", "dummy OPENROUTER_API_KEY": "sk-or-v1-scandummy", "dummy BYTEZ_KEY": "scandummybytez",
           "dummy DATABASE_URL": "SCANDUMMYPW", "dummy SUPABASE_SERVICE_ROLE_KEY": "scan-service-role-DUMMY"}
patterns = {
    "postgres URL": re.compile(r"postgres(?:ql)?(?:\+asyncpg)?://"),
    "service_role": re.compile(r"service_role"),
    "OpenRouter key": re.compile(r"sk-or-v1-[A-Za-z0-9]{16,}"),
    "sk- key": re.compile(r"\bsk-[A-Za-z0-9_-]{24,}"),
    "Nebius-style key": re.compile(r"\bv1\.[A-Za-z0-9_-]{40,}"),
    "JWT": re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    "secret env name": re.compile(r"NEBIUS_API_KEY|OPENROUTER_API_KEY|BYTEZ_[A-Z_]*KEY|SUPABASE_DB_PASSWORD|SERVICE_ROLE_KEY|QLOO_API_KEY"),
}
TOKEN = re.compile(r"[A-Za-z0-9_\-\.]{16,}")


def masked(text: str, start: int, end: int) -> str:
    snippet = text[max(0, start - 40) : end + 40].replace("\n", " ")
    return TOKEN.sub("<tok>", snippet)


files = [p for p in next_dir.rglob("*") if p.is_file() and p.suffix in {".js", ".json", ".html", ".txt", ".map", ".rsc", ".body", ".meta", ".css", ".mjs"}]
leaks, pattern_hits, publishable_files = [], [], 0
for path in files:
    text = path.read_text(encoding="utf-8", errors="ignore")
    if publishable and publishable in text:
        publishable_files += 1
        text = text.replace(publishable, "<PUBLISHABLE_KEY>")
    for name, value in {**real_secrets, **dummies}.items():
        if value in text:
            leaks.append((name, path.relative_to(next_dir)))
    for name, regex in patterns.items():
        for match in regex.finditer(text):
            pattern_hits.append((name, path.relative_to(next_dir), masked(text, match.start(), match.end())))

print(f"files scanned: {len(files)} in {next_dir}")
print(f"publishable key present in {publishable_files} file(s) (allowed)")
print(f"configured/dummy secret values found: {len(leaks)}")
for name, path in leaks:
    print(f"  LEAK {name} in {path}")
print(f"pattern hits: {len(pattern_hits)}")
for name, path, context in pattern_hits[:40]:
    print(f"  {name}: {path}: ...{context}...")
