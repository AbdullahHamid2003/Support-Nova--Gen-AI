#!/usr/bin/env python
"""Capture UI screenshots into ``screenshots/`` and report browser console errors for every page.

    backend/.venv/Scripts/python.exe scripts/capture_screenshots.py [--base http://127.0.0.1:5173] [--only NAME]

Drives a locally installed Chrome or Edge in headless mode over the DevTools protocol, with a throwaway
profile (the user's own browser profile is never touched). Each role signs in through the API with the
demo password (DEMO_PASSWORD, default Lumora#Demo2026); the session cookie is handed to the browser.
Exit code 1 if any page logged a console error or an uncaught exception.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import itertools
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import websockets

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "screenshots"
PASSWORD = os.environ.get("DEMO_PASSWORD", "Lumora#Demo2026")
BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "google-chrome", "chromium", "chromium-browser", "microsoft-edge",
]


@dataclass
class Shot:
    name: str
    role: str | None          # None = signed out
    path: str
    theme: str = "light"
    width: int = 1440
    height: int = 900
    full_page: bool = False
    click: str | tuple[str, ...] | None = None  # text of the tab(s)/button(s) to click, in order, before capturing
    wait_for: str | None = None  # text that must be on the page before capturing


def shots(refs: dict[str, str]) -> list[Shot]:
    c, esc, inj, cust = refs["complaint"], refs["escalated"], refs["injection"], refs["customer_complaint"]
    return [
        Shot("01-login", None, "/login"),
        Shot("02-login-dark", None, "/login", theme="dark"),
        Shot("03-customer-dashboard", "customer", "/"),
        Shot("04-customer-submit-complaint", "customer", "/complaints/new"),
        Shot("05-customer-complaint-view", "customer", f"/complaints/{cust}", full_page=True),
        Shot("06-agent-dashboard", "agent", "/"),
        Shot("07-complaint-list", "admin", "/complaints"),
        Shot("08-complaint-detail-final-intelligence", "admin", f"/complaints/{esc}", full_page=True),
        Shot("09-complaint-ai-vs-rules", "admin", f"/complaints/{esc}", click="AI vs rules", full_page=True),
        Shot("10-complaint-evidence", "admin", f"/complaints/{c}", click="Evidence", full_page=True),
        Shot("11-prompt-injection-flagged", "admin", f"/complaints/{inj}", full_page=True),
        Shot("12-review-queue", "reviewer", "/reviews"),
        Shot("13-review-workspace", "reviewer", f"/reviews/{refs['review']}", full_page=True),
        Shot("14-manager-dashboard", "manager", "/", full_page=True),
        Shot("15-knowledge-base", "admin", "/knowledge"),
        Shot("16-policy-document-versions", "admin", f"/knowledge/{refs['document']}", full_page=True),
        Shot("17-rule-matrix", "admin", "/rules"),
        Shot("18-rule-simulator", "admin", "/rules", click=("Rule simulator", "Calm wording, real hazard", "Run simulation"), full_page=True),
        Shot("19-prompts-and-ai", "admin", "/prompts"),
        Shot("20-analytics", "manager", "/analytics", full_page=True),
        Shot("21-analytics-ai-vs-rules", "manager", "/analytics", click="AI vs rules", full_page=True),
        Shot("22-reports-and-exports", "manager", "/reports", full_page=True),
        Shot("23-evaluation-runs", "admin", "/evaluation"),
        Shot("24-evaluation-run-holdout", "admin", f"/evaluation/{refs['run']}", full_page=True),
        Shot("25-adversarial-lab", "admin", "/lab", full_page=True),
        Shot("26-audit-log", "admin", "/audit"),
        Shot("27-administration", "admin", "/admin"),
        Shot("28-dashboard-dark", "admin", "/", theme="dark", full_page=True),
        Shot("29-complaint-detail-dark", "admin", f"/complaints/{esc}", theme="dark"),
        Shot("30-mobile-dashboard", "agent", "/", width=390, height=844, full_page=True),
        Shot("31-mobile-complaint-detail", "customer", f"/complaints/{cust}", width=390, height=844, full_page=True),
    ]


def find_browser() -> str:
    for candidate in BROWSERS:
        path = candidate if Path(candidate).exists() else shutil.which(candidate)
        if path:
            return str(path)
    sys.exit("No Chrome/Chromium/Edge found for headless capture.")


class CDP:
    def __init__(self, ws: Any) -> None:
        self.ws = ws
        self.ids = itertools.count(1)
        self.errors: list[str] = []
        self.pending: dict[int, asyncio.Future[Any]] = {}
        self.reader = asyncio.create_task(self._read())

    async def _read(self) -> None:
        async for raw in self.ws:
            msg = json.loads(raw)
            if "id" in msg and msg["id"] in self.pending:
                self.pending.pop(msg["id"]).set_result(msg)
            elif msg.get("method") == "Runtime.exceptionThrown":
                d = msg["params"]["exceptionDetails"]
                self.errors.append("exception: " + str((d.get("exception") or {}).get("description") or d.get("text"))[:300])
            elif msg.get("method") == "Runtime.consoleAPICalled" and msg["params"]["type"] in ("error", "assert"):
                args = msg["params"].get("args", [])
                self.errors.append("console.error: " + " ".join(str(a.get("value", a.get("description", ""))) for a in args)[:300])
            elif msg.get("method") == "Log.entryAdded" and msg["params"]["entry"]["level"] == "error":
                e = msg["params"]["entry"]
                if "favicon" not in e.get("url", ""):
                    self.errors.append(f"log: {e.get('text', '')[:200]} {e.get('url', '')}")

    async def send(self, method: str, **params: Any) -> dict[str, Any]:
        i = next(self.ids)
        fut: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self.pending[i] = fut
        await self.ws.send(json.dumps({"id": i, "method": method, "params": params}))
        msg = await asyncio.wait_for(fut, 30)
        if "error" in msg:
            raise RuntimeError(f"{method}: {msg['error']}")
        return dict(msg.get("result", {}))

    async def evaluate(self, expression: str) -> Any:
        r = await self.send("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True)
        return r.get("result", {}).get("value")


SETTLED = """(() => {
  const busy = document.querySelectorAll('.animate-pulse, [aria-busy="true"], [data-loading="true"]').length;
  return document.readyState === 'complete' && busy === 0 && !!document.querySelector('#root > *');
})()"""


async def settle(cdp: CDP, wait_for: str | None = None, timeout: float = 15.0) -> None:
    end = time.monotonic() + timeout
    await asyncio.sleep(0.6)
    while time.monotonic() < end:
        ok = await cdp.evaluate(SETTLED)
        if ok and wait_for:
            ok = await cdp.evaluate(f"document.body.innerText.includes({json.dumps(wait_for)})")
        if ok:
            break
        await asyncio.sleep(0.3)
    await asyncio.sleep(0.8)  # let charts finish their entry animation


def login(base: str, role: str) -> dict[str, str]:
    r = httpx.post(f"{base}/api/v1/auth/login", json={"email": f"{role}@lumora.example", "password": PASSWORD}, timeout=30)
    r.raise_for_status()
    return {k: v for k, v in r.cookies.items()}


async def capture(base: str, shot: Shot, cdp: CDP, cookies: dict[str | None, dict[str, str]]) -> list[str]:
    await cdp.send("Network.clearBrowserCookies")
    for name, value in (cookies.get(shot.role) or {}).items():
        await cdp.send("Network.setCookie", name=name, value=value, url=base, path="/")
    await cdp.send("Emulation.setDeviceMetricsOverride", width=shot.width, height=shot.height, deviceScaleFactor=1,
                   mobile=shot.width < 768)
    await cdp.send("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": shot.theme},
                                                            {"name": "prefers-reduced-motion", "value": "reduce"}])
    await cdp.send("Page.navigate", url=base + "/login")
    await asyncio.sleep(0.3)
    await cdp.evaluate(f"localStorage.setItem('sn-theme', {json.dumps(shot.theme)}); sessionStorage.clear(); true")
    cdp.errors.clear()
    await cdp.send("Page.navigate", url=base + shot.path)
    await settle(cdp, shot.wait_for)
    for label in ((shot.click,) if isinstance(shot.click, str) else shot.click or ()):
        # a real pointer click (Radix tabs select on mousedown, which element.click() does not fire)
        box = await cdp.evaluate(f"""(() => {{
          const want = {json.dumps(label)}, all = [...document.querySelectorAll('[role=tab], button, a')];
          const el = all.find(e => e.innerText.trim() === want) || all.find(e => e.innerText.trim().startsWith(want));
          if (!el) return null; el.scrollIntoView({{block: 'center'}}); const r = el.getBoundingClientRect();
          return {{x: r.x + r.width / 2, y: r.y + r.height / 2, tab: el.getAttribute('role') === 'tab'}}; }})()""")
        if not box:
            cdp.errors.append(f"could not find '{label}' to click")
            break
        for kind in ("mouseMoved", "mousePressed", "mouseReleased"):
            await cdp.send("Input.dispatchMouseEvent", type=kind, x=box["x"], y=box["y"], button="left", clickCount=1)
        await settle(cdp)
        if box["tab"] and not await cdp.evaluate(f"""[...document.querySelectorAll('[role=tab][data-state=active]')]
              .some(e => e.innerText.trim().startsWith({json.dumps(label)}))"""):
            cdp.errors.append(f"tab '{label}' did not become active")
    await cdp.evaluate("window.scrollTo(0, 0)")
    if shot.full_page:
        height = await cdp.evaluate("Math.min(document.documentElement.scrollHeight, 4200)")
        await cdp.send("Emulation.setDeviceMetricsOverride", width=shot.width, height=int(height or shot.height),
                       deviceScaleFactor=1, mobile=shot.width < 768)
        await asyncio.sleep(0.8)
    data = await cdp.send("Page.captureScreenshot", format="png")
    (OUT / f"{shot.name}.png").write_bytes(base64.b64decode(data["data"]))
    path_now = await cdp.evaluate("location.pathname")
    problems = list(cdp.errors)
    if shot.role is None:  # signed out: the session probe answering 401 is the expected outcome
        problems = [p for p in problems if not ("401" in p and "/api/v1/auth/me" in p)]
    if shot.role and path_now == "/login":
        problems.append("redirected to /login (session not accepted)")
    return problems


def sample_refs(base: str, admin_cookies: dict[str, str]) -> dict[str, str]:
    c = httpx.Client(base_url=f"{base}/api/v1", cookies=admin_cookies, timeout=30)
    def first(path: str, **params: Any) -> dict[str, Any]:
        items = c.get(path, params=params).json().get("items", [])
        return items[0] if items else {}
    refs = {
        "escalated": first("/complaints", status="Escalated", source="dataset", page_size=1).get("complaint_ref", ""),
        "complaint": first("/complaints", verification="Verified", source="dataset", page_size=1).get("complaint_ref", ""),
        "injection": first("/complaints", injection="true", source="dataset", page_size=1).get("complaint_ref", ""),
        "review": str(first("/reviews", status="pending").get("id", "")),
        # the newest completed run - a cancelled or partial run is not representative evidence
        "run": str(next((r["id"] for r in c.get("/evaluation/runs").json().get("items", []) if r.get("status") == "completed"),
                        first("/evaluation/runs").get("id", ""))),
        "document": "REF-POL-02",
    }
    customer = httpx.Client(base_url=f"{base}/api/v1", cookies=login(base, "customer"), timeout=30)
    items = customer.get("/complaints", params={"page_size": 5}).json().get("items", [])
    refs["customer_complaint"] = items[0]["complaint_ref"] if items else ""
    return refs


async def main_async(args: argparse.Namespace) -> int:
    OUT.mkdir(exist_ok=True)
    roles = ["customer", "agent", "reviewer", "manager", "admin"]
    cookies: dict[str | None, dict[str, str]] = {r: login(args.base, r) for r in roles}
    cookies[None] = {}
    refs = sample_refs(args.base, cookies["admin"])
    print("sample records:", refs)
    plan = [s for s in shots(refs) if not args.only or args.only in s.name]
    profile = tempfile.mkdtemp(prefix="sn-shots-")
    port = 9333
    proc = subprocess.Popen([find_browser(), "--headless=new", f"--remote-debugging-port={port}", f"--user-data-dir={profile}",  # noqa: S603
                             "--no-first-run", "--no-default-browser-check", "--hide-scrollbars", "--disable-extensions",
                             "--window-size=1440,900", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    failures = 0
    try:
        for _ in range(50):
            with contextlib.suppress(httpx.HTTPError):
                targets = httpx.get(f"http://127.0.0.1:{port}/json/list", timeout=2).json()
                page = next(t for t in targets if t["type"] == "page")
                break
            time.sleep(0.2)
        else:
            raise RuntimeError("browser did not start")
        async with websockets.connect(page["webSocketDebuggerUrl"], max_size=64 * 1024 * 1024) as ws:
            cdp = CDP(ws)
            for domain in ("Page", "Runtime", "Log", "Network"):
                await cdp.send(f"{domain}.enable")
            for shot in plan:
                problems = await capture(args.base, shot, cdp, cookies)
                status = "ok" if not problems else "PROBLEMS"
                failures += bool(problems)
                print(f"{status:8} {shot.name}.png  ({shot.role or 'signed out'}, {shot.theme}, {shot.width}px)")
                for p in problems:
                    print(f"         - {p}")
            cdp.reader.cancel()
    finally:
        proc.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(10)
        shutil.rmtree(profile, ignore_errors=True)
    print(f"\n{len(plan)} screenshots in screenshots/, {failures} with problems")
    return 1 if failures else 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="http://127.0.0.1:5173", help="frontend URL (Vite dev server or FastAPI serving the build)")
    ap.add_argument("--only", default=None, help="capture only shots whose name contains this text")
    sys.exit(asyncio.run(main_async(ap.parse_args())))


if __name__ == "__main__":
    main()
