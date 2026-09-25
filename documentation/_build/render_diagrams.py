"""Render every documentation/diagrams/**/*.mmd to .svg (PDF/HTML) and .png (DOCX) with Mermaid in headless Chrome.

    backend/.venv/Scripts/python.exe documentation/_build/render_diagrams.py [--force] [--only NAME[,NAME...]]

Mermaid is loaded from documentation/_build/.tools/node_modules/mermaid (installed on first use with npm).
Unchanged diagrams are skipped (content hash in .render-cache.json). Exit code 1 if any diagram fails to render.
Each run uses its own browser port and page file, so several runs can work in parallel. For every diagram the
script prints its size and the text size it will have when printed on an A4 page ("print 6.8pt"); a figure
below 6.5 pt is flagged "TOO SMALL" and should be simplified or split.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import hashlib
import itertools
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx
import websockets

DOC = Path(__file__).resolve().parents[1]
TOOLS = DOC / "_build" / ".tools"
MERMAID_VERSION = "11.4.1"
BROWSERS = [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            "google-chrome", "chromium", "microsoft-edge"]
THEME = {
    "startOnLoad": False, "theme": "base", "securityLevel": "loose",
    "fontFamily": "'Segoe UI', 'Helvetica Neue', Arial, sans-serif",
    "themeVariables": {
        "fontSize": "15px", "primaryColor": "#F8FAFC", "primaryTextColor": "#0F172A", "primaryBorderColor": "#64748B",
        "lineColor": "#475569", "secondaryColor": "#EEF0FF", "tertiaryColor": "#F8FAFC", "clusterBkg": "#F8FAFC",
        "clusterBorder": "#CBD5E1", "edgeLabelBackground": "#FFFFFF", "titleColor": "#0F172A",
        "actorBkg": "#EEF0FF", "actorBorder": "#4F46E5", "actorTextColor": "#1E1B4B", "signalColor": "#334155",
        "signalTextColor": "#0F172A", "labelBoxBkgColor": "#F1F5F9", "labelBoxBorderColor": "#94A3B8",
        "noteBkgColor": "#FEF3E2", "noteBorderColor": "#B45309", "noteTextColor": "#431407",
        "activationBkgColor": "#E7F6EC", "activationBorderColor": "#15803D", "sequenceNumberColor": "#FFFFFF",
    },
    "flowchart": {"htmlLabels": True, "curve": "basis", "padding": 14, "nodeSpacing": 45, "rankSpacing": 55, "useMaxWidth": False,
                  "wrappingWidth": 220},
    "sequence": {"useMaxWidth": False, "mirrorActors": False, "showSequenceNumbers": True, "wrap": True, "width": 170,
                 "messageFontSize": 14, "noteFontSize": 13, "actorFontSize": 14},
    "er": {"useMaxWidth": False, "fontSize": 13},
    "state": {"useMaxWidth": False},
    "class": {"useMaxWidth": False},
}


def ensure_mermaid() -> Path:
    js = TOOLS / "node_modules" / "mermaid" / "dist" / "mermaid.min.js"
    if not js.exists():
        TOOLS.mkdir(parents=True, exist_ok=True)
        npm = shutil.which("npm") or shutil.which("npm.cmd")
        if not npm:
            sys.exit("npm is required to install mermaid")
        subprocess.run([npm, "install", "--no-audit", "--no-fund", "--prefix", str(TOOLS), f"mermaid@{MERMAID_VERSION}"], check=True)  # noqa: S603
    return js


def find_browser() -> str:
    for b in BROWSERS:
        if Path(b).exists() or shutil.which(b):
            return b
    sys.exit("Chrome or Edge is required")


class CDP:
    def __init__(self, ws: Any) -> None:
        self.ws, self.ids, self.pending = ws, itertools.count(1), {}
        self.reader = asyncio.create_task(self._read())

    async def _read(self) -> None:
        async for raw in self.ws:
            msg = json.loads(raw)
            if "id" in msg and msg["id"] in self.pending:
                self.pending.pop(msg["id"]).set_result(msg)

    async def send(self, method: str, **params: Any) -> dict[str, Any]:
        i = next(self.ids)
        fut = asyncio.get_running_loop().create_future()
        self.pending[i] = fut
        await self.ws.send(json.dumps({"id": i, "method": method, "params": params}))
        msg = await asyncio.wait_for(fut, 120)
        if "error" in msg:
            raise RuntimeError(f"{method}: {msg['error']}")
        return dict(msg.get("result", {}))

    async def evaluate(self, expression: str) -> Any:
        r = await self.send("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True)
        if "exceptionDetails" in r:
            raise RuntimeError(str(r["exceptionDetails"])[:500])
        return r.get("result", {}).get("value")


PAGE = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;background:#fff} #holder{display:inline-block;padding:16px;background:#fff}
</style><script src="%s"></script></head><body><div id="holder"></div><script>
mermaid.initialize(%s);
window.renderOne = async (id, code) => {
  const holder = document.getElementById('holder');
  holder.innerHTML = '';
  try {
    const out = await mermaid.render(id, code);
    holder.innerHTML = out.svg;
    const el = holder.querySelector('svg');
    const vb = el.viewBox && el.viewBox.baseVal;
    if (vb && vb.width) { el.setAttribute('width', Math.ceil(vb.width)); el.setAttribute('height', Math.ceil(vb.height)); }
    el.style.maxWidth = 'none';
    const r = holder.getBoundingClientRect();
    return {ok: true, svg: new XMLSerializer().serializeToString(el), x: r.left, y: r.top, w: Math.ceil(r.width), h: Math.ceil(r.height)};
  } catch (e) {
    document.querySelectorAll('[id^="d' + id + '"], #' + id).forEach(n => n.remove());
    return {ok: false, error: String((e && e.message) || e)};
  }
};
window.ready = true;
</script></body></html>"""


# A4 portrait text block used by build_report.py (176 x 225 mm for a figure) and the 15 px diagram font.
PRINT_W_MM, PRINT_H_MM, FONT_PX, MIN_PT = 176, 225, 15, 6.5


def print_pt(w: int, h: int) -> float:
    return round(FONT_PX * min(PRINT_W_MM / w, PRINT_H_MM / h) * 2.8346, 1)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def render_all(files: list[Path]) -> int:
    js = ensure_mermaid()
    profile = tempfile.mkdtemp(prefix="sn-mermaid-")
    page_file = Path(profile) / "render.html"
    page_file.write_text(PAGE % (js.as_uri(), json.dumps(THEME)), encoding="utf-8")
    port = free_port()
    proc = subprocess.Popen([find_browser(), "--headless=new", f"--remote-debugging-port={port}", f"--user-data-dir={profile}",  # noqa: S603
                             "--no-first-run", "--no-default-browser-check", "--allow-file-access-from-files", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    failures = 0
    try:
        for _ in range(100):
            with contextlib.suppress(Exception):
                targets = httpx.get(f"http://127.0.0.1:{port}/json/list", timeout=2).json()
                page = next(t for t in targets if t["type"] == "page")
                break
            time.sleep(0.2)
        else:
            raise RuntimeError("browser did not start")
        async with websockets.connect(page["webSocketDebuggerUrl"], max_size=256 * 1024 * 1024) as ws:
            cdp = CDP(ws)
            await cdp.send("Page.enable")
            await cdp.send("Runtime.enable")
            await cdp.send("Page.navigate", url=page_file.as_uri())
            for _ in range(100):
                if await cdp.evaluate("window.ready === true && typeof mermaid !== 'undefined'"):
                    break
                await asyncio.sleep(0.1)
            for n, f in enumerate(files):
                code = f.read_text(encoding="utf-8").strip()
                res = await cdp.evaluate(f"window.renderOne({json.dumps('m' + str(n))}, {json.dumps(code)})")
                rel = f.relative_to(DOC).as_posix()
                if not res or not res.get("ok"):
                    failures += 1
                    print(f"FAIL {rel}: {(res or {}).get('error', 'no result')[:400]}")
                    continue
                svg = res["svg"]
                if "xmlns=" not in svg[:300]:
                    svg = svg.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"', 1)
                f.with_suffix(".svg").write_text('<?xml version="1.0" encoding="UTF-8"?>\n' + svg, encoding="utf-8")
                w, h = max(res["w"], 50), max(res["h"], 50)
                await cdp.send("Emulation.setDeviceMetricsOverride", width=min(w + 40, 6000), height=min(h + 40, 12000),
                               deviceScaleFactor=2, mobile=False)
                shot = await cdp.send("Page.captureScreenshot", format="png", captureBeyondViewport=True,
                                      clip={"x": res["x"], "y": res["y"], "width": w, "height": h, "scale": 1})
                f.with_suffix(".png").write_bytes(base64.b64decode(shot["data"]))
                pt = print_pt(w, h)
                print(f"ok   {rel}  ({w}x{h}, print {pt}pt{'  TOO SMALL - simplify or split' if pt < MIN_PT else ''})")
    finally:
        proc.terminate()
        with contextlib.suppress(Exception):
            proc.wait(5)
        shutil.rmtree(profile, ignore_errors=True)
    return failures


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--only")
    args = ap.parse_args()
    cache_file = DOC / "_build" / ".render-cache.json"
    try:
        cache = json.loads(cache_file.read_text())
    except Exception:  # noqa: BLE001 - missing or half-written cache: render again
        cache = {}
    only = [o.strip() for o in (args.only or "").split(",") if o.strip()]
    todo = []
    for f in sorted((DOC / "diagrams").rglob("*.mmd")):
        if only and not any(o in f.name for o in only):
            continue
        digest = hashlib.sha256((f.read_text(encoding="utf-8") + json.dumps(THEME)).encode()).hexdigest()
        rel = f.relative_to(DOC).as_posix()
        if args.force or cache.get(rel) != digest or not f.with_suffix(".svg").exists() or not f.with_suffix(".png").exists():
            todo.append((f, rel, digest))
    print(f"{len(todo)} diagram(s) to render")
    failures = asyncio.run(render_all([f for f, _r, _d in todo])) if todo else 0
    try:
        cache = {**json.loads(cache_file.read_text()), **{}}
    except Exception:  # noqa: BLE001
        pass
    for f, rel, digest in todo:
        if f.with_suffix(".svg").exists() and f.with_suffix(".svg").stat().st_mtime >= f.stat().st_mtime:
            cache[rel] = digest
    tmp = cache_file.with_name(f".render-cache.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(cache, indent=1))
    os.replace(tmp, cache_file)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
