#!/usr/bin/env python3
"""/chro-based portfolio informer.

Uses the portfolio-review skill's canonical browser sources:
- EVM: https://debank.com/profile/<address>
- Solana: https://jup.ag/portfolio/<address>

State is privacy-safe: only hashes/timestamps/decision metadata, no addresses,
raw page text, balances, amounts, totals, or token lists.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import websockets

HERMES_HOME = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
SKILL_DIR = Path(os.environ.get("PORTFOLIO_REVIEW_SKILL_DIR") or HERMES_HOME / "skills" / "private" / "portfolio-review")
ADDRESSES_PATH = SKILL_DIR / "addresses.conf"
STATE_PATH = SKILL_DIR / "chro-informer-state.json"
CAMOFOX_URL = os.environ.get("CAMOFOX_URL", "http://127.0.0.1:9377").rstrip("/")
CAMOFOX_USER_ID = os.environ.get("PORTFOLIO_REVIEW_CAMOFOX_USER_ID") or "portfolio-review"
CAMOFOX_SESSION_KEY = os.environ.get("PORTFOLIO_REVIEW_CAMOFOX_SESSION_KEY") or "weekly-informer"
CHROMIUM_BIN = os.environ.get("PORTFOLIO_REVIEW_CHROMIUM_BIN") or "chromium"
CHROMIUM_PROFILE = Path(os.environ.get("PORTFOLIO_REVIEW_CHROMIUM_PROFILE") or Path.home() / ".config" / "chromium-persistent")

NOISE_RE = re.compile(r"cookie|privacy|terms|connect wallet|sign in|log in|download app|share", re.I)
MONEY_RE = re.compile(r"(?:\$|USD\s*)([0-9][0-9,]*(?:\.[0-9]+)?)")
PCT_RE = re.compile(r"[-+]?\d+(?:\.\d+)?%")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def short_hash(text: str) -> str:
    return sha(text)[:24]


def read_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(path.read_text("utf-8"))
    except FileNotFoundError:
        return fallback


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")


def read_addresses() -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for line in ADDRESSES_PATH.read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, address = [part.strip() for part in line.split("=", 1)]
        kind = "evm" if key.startswith("evm_") or key == "evm2" else "sol" if key.startswith("sol_") else ""
        if not kind:
            continue
        sig = f"{kind}:{address.lower()}"
        if sig in seen:
            continue
        seen.add(sig)
        entries.append({"kind": kind, "key": key, "address": address})
    return entries


def fetch_json(path: str, timeout: int = 10) -> Any:
    with urllib.request.urlopen(f"{CAMOFOX_URL}{path}", timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def post_json(path: str, payload: dict[str, Any], timeout: int = 30) -> Any:
    req = urllib.request.Request(
        f"{CAMOFOX_URL}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}




def delete_json(path: str, payload: dict[str, Any], timeout: int = 15) -> Any:
    req = urllib.request.Request(
        f"{CAMOFOX_URL}{path}",
        data=json.dumps(payload).encode('utf-8'),
        headers={"content-type": "application/json"},
        method="DELETE",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode('utf-8')
        return json.loads(raw) if raw else {}


def close_camofox_portfolio_group() -> None:
    try:
        delete_json(f"/tabs/group/{urllib.parse.quote(CAMOFOX_SESSION_KEY)}", {"userId": CAMOFOX_USER_ID}, timeout=15)
    except Exception:
        pass

def ensure_chro() -> None:
    # Hermes migration: the legacy agent /chro manager is gone. Use the already-running
    # Hermes Camofox service instead. It exposes legacy agent-compatible snapshot APIs.
    health = fetch_json("/health", timeout=5)
    if not health.get("ok") or not health.get("running"):
        raise RuntimeError(f"Camofox service is not healthy: {health}")


_PORTFOLIO_TAB_ID: str | None = None


def create_tab(url: str) -> dict[str, Any]:
    payload = {"userId": CAMOFOX_USER_ID, "sessionKey": CAMOFOX_SESSION_KEY, "url": url}
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            return post_json("/tabs", payload, timeout=45)
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code == 429:
                close_camofox_portfolio_group()
                time.sleep(1 + attempt)
                continue
            raise
        except Exception as exc:
            last_exc = exc
            # Fallback to the documented legacy agent-compatible endpoint.
            try:
                return post_json("/tabs/open", {"userId": CAMOFOX_USER_ID, "url": url}, timeout=45)
            except urllib.error.HTTPError as fallback_exc:
                last_exc = fallback_exc
                if fallback_exc.code == 429:
                    close_camofox_portfolio_group()
                    time.sleep(1 + attempt)
                    continue
                raise
    if last_exc:
        raise last_exc
    raise RuntimeError('failed to create Camofox tab')


def navigate_tab(tab_id: str, url: str) -> None:
    post_json(f"/tabs/{urllib.parse.quote(tab_id)}/navigate", {"userId": CAMOFOX_USER_ID, "url": url}, timeout=45)


def get_snapshot(tab_id: str) -> dict[str, Any]:
    query = urllib.parse.urlencode({"userId": CAMOFOX_USER_ID})
    return fetch_json(f"/tabs/{urllib.parse.quote(tab_id)}/snapshot?{query}", timeout=30)


async def open_and_text(url: str, wait_seconds: int) -> tuple[str, str]:
    global _PORTFOLIO_TAB_ID
    if not _PORTFOLIO_TAB_ID:
        tab = create_tab(url)
        _PORTFOLIO_TAB_ID = str(tab.get("tabId") or tab.get("id") or tab.get("targetId") or "")
        if not _PORTFOLIO_TAB_ID:
            raise RuntimeError(f"created tab has no tab id: {tab}")
    else:
        navigate_tab(_PORTFOLIO_TAB_ID, url)
    await asyncio.sleep(max(1, wait_seconds))
    snapshot = get_snapshot(_PORTFOLIO_TAB_ID)
    text = str(snapshot.get("snapshot") or "")
    title = ""
    for line in text.splitlines():
        m = re.search(r'heading "([^"]+)"', line)
        if m:
            title = m.group(1)
            break
    return title, text



def free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return int(sock.getsockname()[1])


async def cdp_eval_page_text(port: int, wait_seconds: int) -> tuple[str, str]:
    deadline = time.time() + max(30, wait_seconds + 30)
    tabs: list[dict[str, Any]] = []
    while time.time() < deadline:
        try:
            tabs = fetch_json(f"/json", timeout=1) if False else json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=2).read().decode('utf-8'))
            if any(t.get('type') == 'page' for t in tabs):
                break
        except Exception:
            await asyncio.sleep(1)
    page = next((t for t in tabs if t.get('type') == 'page'), None)
    if not page:
        raise RuntimeError('Chromium CDP page not available')
    async with websockets.connect(page['webSocketDebuggerUrl']) as ws:
        msg_id = 0
        async def send(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
            nonlocal msg_id
            msg_id += 1
            current = msg_id
            await ws.send(json.dumps({'id': current, 'method': method, 'params': params or {}}))
            while True:
                message = json.loads(await ws.recv())
                if message.get('id') == current:
                    return message
        await send('Runtime.enable')
        # Jupiter Portfolio may pass Turnstile and then fetch positions asynchronously.
        # Wait in the real headed Chromium profile before extracting body text.
        expr = (
            "new Promise(resolve => setTimeout(() => resolve({"
            "title: document.title || '',"
            "text: document.body ? document.body.innerText : ''"
            "}), " + str(max(5, wait_seconds) * 1000) + "))"
        )
        result = await send('Runtime.evaluate', {'expression': expr, 'awaitPromise': True, 'returnByValue': True})
        value = (((result.get('result') or {}).get('result') or {}).get('value') or {})
        return str(value.get('title') or ''), str(value.get('text') or '')


async def open_solana_chromium_text(address: str, wait_seconds: int) -> tuple[str, str]:
    url = f"https://jup.ag/portfolio/{address}"
    port = free_local_port()
    CHROMIUM_PROFILE.mkdir(parents=True, exist_ok=True)
    cmd = [
        'xvfb-run', '-a', CHROMIUM_BIN,
        '--no-sandbox', '--disable-gpu',
        f'--remote-debugging-port={port}',
        f'--user-data-dir={CHROMIUM_PROFILE}',
        url,
    ]
    env = os.environ.copy()
    # In the Telegram/terminal environment DBUS_SESSION_BUS_ADDRESS can point at a
    # session bus that makes headed Chromium under xvfb start with a blank page.
    # The cron/browser check does not need DBus, so keep the launched browser isolated.
    env.pop('DBUS_SESSION_BUS_ADDRESS', None)
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, env=env)
    try:
        return await cdp_eval_page_text(port, wait_seconds)
    finally:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except Exception:
            proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except Exception:
                proc.kill()


def clean_lines(text: str) -> list[str]:
    out: list[str] = []
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        # Camofox snapshots are accessibility-tree lines. Keep the human text and
        # drop roles/refs/URLs/addresses so notifications stay useful and private.
        # Drop accessibility-tree/list bullets, but do not turn negative money
        # values like "-$44.99" into positive values.
        line = re.sub(r"^-\s+", "", line)
        if line.startswith("/url:") or line.startswith("- /url:"):
            continue
        m = re.match(r'^(?:heading|paragraph|text|button|link)\s+"([^"]+)"(?:\s+\[[^\]]+\])?:?$', line)
        if m:
            line = m.group(1)
        else:
            line = re.sub(r"^(?:paragraph|text|button|link):\s*", "", line)
        line = re.sub(r"\[[a-z]\d+\]", "", line).strip()
        if re.search(r"0x[a-fA-F0-9]{12,}", line):
            continue
        if re.search(r"\b[1-9A-HJ-NP-Za-km-z]{3,}\.\.\.[1-9A-HJ-NP-Za-km-z]{3,}\b", line):
            continue
        if re.search(r"[1-9A-HJ-NP-Za-km-z]{24,}", line) and not MONEY_RE.search(line):
            continue
        if len(line) < 2 or len(line) > 140:
            continue
        if NOISE_RE.search(line):
            continue
        out.append(line)
    return out


def useful_lines(text: str, limit: int = 8) -> list[str]:
    lines = clean_lines(text)
    scored: list[tuple[int, str]] = []
    keywords = re.compile(r"net worth|portfolio|holdings|assets|token|pnl|claimable|staked|defi|wallet|balance|worth", re.I)
    for line in lines:
        score = 0
        if MONEY_RE.search(line):
            score += 4
        if PCT_RE.search(line):
            score += 2
        if keywords.search(line):
            score += 3
        if re.fullmatch(r"[A-Z0-9]{2,12}", line):
            score += 1
        if score:
            scored.append((score, line))
    # Keep original-ish order for equal scores, de-dupe text.
    seen: set[str] = set()
    picked: list[str] = []
    for _, line in sorted(enumerate(scored), key=lambda x: (-x[1][0], x[0])):
        value = line[1]
        if value.lower() in seen:
            continue
        seen.add(value.lower())
        picked.append(value)
        if len(picked) >= limit:
            break
    return picked



def normalize_line_for_hash(line: str) -> str:
    def money_repl(match: re.Match[str]) -> str:
        raw = match.group(1).replace(',', '')
        try:
            value = float(raw)
        except ValueError:
            return '$?'
        step = 100 if value >= 1000 else 25 if value >= 250 else 10 if value >= 50 else 5 if value >= 10 else 1
        return f"${round(value / step) * step:g}"

    def pct_repl(match: re.Match[str]) -> str:
        raw = match.group(0).rstrip('%')
        try:
            value = float(raw)
        except ValueError:
            return '?%'
        return f"{round(value):g}%"

    value = MONEY_RE.sub(money_repl, line.lower())
    value = PCT_RE.sub(pct_repl, value)
    value = re.sub(r"\b\d+\s+days? ago\b", "N days ago", value)
    return value

def source_fingerprint(items: list[dict[str, Any]]) -> str:
    # Hash only stable-ish extracted portfolio lines. Do not store raw text.
    # Full SPA text contains timestamps, recommendations, banners and other noise
    # that can change between two consecutive loads and cause false alerts.
    normalized = []
    for item in items:
        lines = useful_lines(item.get("text", ""), limit=24)
        material = "\n".join(normalize_line_for_hash(line) for line in lines)
        normalized.append({"kind": item["kind"], "keyHash": item.get("keyHash"), "hash": short_hash(material)})
    return short_hash(json.dumps(normalized, ensure_ascii=False, sort_keys=True))



def is_money(line: str) -> bool:
    return bool(re.fullmatch(r"[-+]?<?\$[0-9][0-9,]*(?:\.[0-9]+)?[KMB]?", line.strip(), re.I))


def money_value(line: str) -> float:
    m = re.search(r"([-+]?)<?\$([0-9][0-9,]*(?:\.[0-9]+)?)([KMB]?)", line, re.I)
    if not m:
        return 0.0
    value = float(m.group(2).replace(',', ''))
    if m.group(1) == '-':
        value = -value
    mult = {'K': 1_000, 'M': 1_000_000, 'B': 1_000_000_000}.get(m.group(3).upper(), 1)
    return value * mult


def format_usd(value: float) -> str:
    if value >= 1000:
        return f"${value:,.0f}"
    if value >= 100:
        return f"${value:,.1f}"
    return f"${value:,.2f}"


def first_money_and_change(line: str) -> tuple[str | None, str | None]:
    money = re.search(r"[-+]?<?\$[0-9][0-9,]*(?:\.[0-9]+)?[KMB]?", line, re.I)
    pct = PCT_RE.search(line)
    return (money.group(0) if money else None, pct.group(0) if pct else None)


def parse_compact_allocations(line: str, limit: int = 6) -> list[str]:
    pattern = re.compile(
        r"([A-Za-z][A-Za-z0-9 ()/_-]{1,30}?)\s+"
        r"(\$[0-9][0-9,]*(?:\.[0-9]+)?[KMB]?)"
        r"(?:\s+([-+]?\d+(?:\.\d+)?%))?(?=\s+[A-Za-z][A-Za-z0-9 ()/_-]{1,30}?\s+\$|$)"
    )
    out: list[str] = []
    for name, value, pct in pattern.findall(line):
        clean_name = re.sub(r"\s+", " ", name).strip()
        if clean_name.lower() in {"img", "link"}:
            continue
        out.append(f"{clean_name}: {value}{f' ({pct})' if pct else ''}")
        if len(out) >= limit:
            break
    return out


def extract_token_rows(lines: list[str], marker: str = 'USD Value', limit: int = 6) -> list[str]:
    start = None
    for idx, line in enumerate(lines):
        if marker == line or marker in line:
            start = idx + 1
            break
    if start is None:
        return []
    rows: list[str] = []
    j = start
    while j < len(lines) - 1 and len(rows) < limit:
        symbol = lines[j]
        if symbol in {'Default', 'Show all'} or symbol.endswith('with small balances are not displayed.'):
            break
        if is_money(symbol) or PCT_RE.fullmatch(symbol) or len(symbol) > 24:
            j += 1
            continue
        merged = lines[j + 1] if j + 1 < len(lines) else ''
        money_values = re.findall(r"\$[0-9][0-9,]*(?:\.[0-9]+)?[KMB]?", merged, re.I)
        if len(money_values) >= 2:
            rows.append(f"{symbol}: {money_values[-1]}")
            j += 2
            continue
        if j + 3 < len(lines):
            price, _amount, value = lines[j + 1], lines[j + 2], lines[j + 3]
            if is_money(price) and is_money(value):
                rows.append(f"{symbol}: {value}")
                j += 4
                continue
        j += 1
    return rows


def summarize_debank_item(text: str) -> dict[str, Any]:
    lines = clean_lines(text)
    total = None
    daily = None
    for line in lines[:80]:
        if 'All Chain' in line:
            break
        money, pct = first_money_and_change(line)
        if money and pct:
            total, daily = money, pct
            break
    chains: list[str] = []
    for i, line in enumerate(lines):
        if line == 'All Chain':
            for nxt in lines[i + 1:i + 6]:
                chains = parse_compact_allocations(nxt, limit=5)
                if chains:
                    break
            break
    wallet_total = None
    for line in lines:
        m = re.search(r"Wallet\s+(\$[0-9][0-9,]*(?:\.[0-9]+)?[KMB]?)", line, re.I)
        if m:
            wallet_total = m.group(1)
            break
    tokens = extract_token_rows(lines, 'USD Value', limit=6)
    protocols: list[str] = []
    for i, line in enumerate(lines):
        if re.search(r"\$[0-9][0-9,]*(?:\.[0-9]+)?[KMB]?\s+(Yield|Staked|Deposit|Lending|Liquidity|Pool)", line, re.I):
            name = None
            for prev in reversed(lines[max(0, i - 4):i]):
                if not is_money(prev) and not prev.startswith('img') and len(prev) <= 40 and prev not in {'link :'}:
                    # DeBank can merge the previous position value into the next protocol name:
                    # "$216.87 Hyperliquid". Keep only the protocol name for display.
                    name = re.sub(r"^[-+]?<?\$[0-9][0-9,]*(?:\.[0-9]+)?[KMB]?\s+", "", prev, flags=re.I).strip()
                    break
            value = re.search(r"[-+]?<?\$[0-9][0-9,]*(?:\.[0-9]+)?[KMB]?", line, re.I)
            if name and value:
                protocols.append(f"{name}: {value.group(0)}")
        if len(protocols) >= 5:
            break
    return {"total": total, "change": daily, "chains": chains, "walletTotal": wallet_total, "tokens": tokens, "protocols": protocols}


def pairs_after(lines: list[str], marker: str, stop_markers: set[str], limit: int = 6) -> list[str]:
    try:
        i = lines.index(marker) + 1
    except ValueError:
        return []
    pairs: list[str] = []
    j = i
    while j < len(lines) - 1 and len(pairs) < limit:
        if lines[j] in stop_markers:
            break
        name = lines[j]
        if is_money(name) or PCT_RE.fullmatch(name) or name.lower().startswith('unfold'):
            j += 1
            continue
        if is_money(lines[j + 1]):
            value = lines[j + 1]
            tail = ''
            if j + 2 < len(lines) and PCT_RE.fullmatch(lines[j + 2]):
                tail = f" ({lines[j + 2]})"
                j += 1
            pairs.append(f"{name}: {value}{tail}")
            j += 2
        else:
            j += 1
    return pairs


def token_rows_after(lines: list[str], marker: str = 'USD Value', limit: int = 6) -> list[str]:
    try:
        i = lines.index(marker) + 1
    except ValueError:
        return []
    rows: list[str] = []
    j = i
    while j < len(lines) - 3 and len(rows) < limit:
        symbol = lines[j]
        if symbol in {'Default', 'Show all'} or symbol.endswith('with small deposits are not displayed.'):
            break
        if is_money(symbol) or PCT_RE.fullmatch(symbol) or len(symbol) > 20:
            j += 1
            continue
        price, amount, value = lines[j + 1], lines[j + 2], lines[j + 3]
        if is_money(price) and is_money(value):
            rows.append(f"{symbol}: {value}")
            j += 4
        else:
            j += 1
    return rows


def format_debank_item(text: str) -> list[str]:
    summary = summarize_debank_item(text)
    out: list[str] = []
    if summary.get('total'):
        change = f" ({summary.get('change')})" if summary.get('change') else ''
        out.append(f"total: {summary['total']}{change}")
    if summary.get('chains'):
        out.append('chains: ' + '; '.join(summary['chains']))
    if summary.get('walletTotal'):
        out.append(f"wallet liquid: {summary['walletTotal']}")
    if summary.get('tokens'):
        out.append('top tokens: ' + '; '.join(summary['tokens'][:5]))
    if summary.get('protocols'):
        out.append('defi/protocols: ' + '; '.join(summary['protocols'][:5]))
    return out or useful_lines(text, limit=6)



def post_public_json(url: str, payload: dict[str, Any], timeout: int = 12) -> Any:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers={'content-type': 'application/json'},
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8'))


def solana_rpc(method: str, params: list[Any]) -> Any:
    data = post_public_json('https://api.mainnet-beta.solana.com', {'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})
    return data.get('result')


def coingecko_sol_price() -> float | None:
    try:
        with urllib.request.urlopen('https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd', timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        return float(data['solana']['usd'])
    except Exception:
        return None


def format_solana_fallback(address: str | None) -> list[str]:
    if not address:
        return []
    out: list[str] = []
    try:
        balance = solana_rpc('getBalance', [address])
        lamports = int((balance or {}).get('value') or 0)
        sol = lamports / 1_000_000_000
        price = coingecko_sol_price()
        if price is not None:
            out.append(f"fallback native SOL: {sol:.4f} SOL ({format_usd(sol * price)})")
        else:
            out.append(f"fallback native SOL: {sol:.4f} SOL")
    except Exception as exc:
        out.append(f"fallback native SOL: не удалось прочитать ({type(exc).__name__})")
    try:
        token_accounts = solana_rpc('getTokenAccountsByOwner', [address, {'programId': 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'}, {'encoding': 'jsonParsed'}])
        values = (token_accounts or {}).get('value') or []
        nonzero = 0
        for account in values:
            amount = (((account.get('account') or {}).get('data') or {}).get('parsed') or {}).get('info', {}).get('tokenAmount', {})
            try:
                if float(amount.get('uiAmount') or 0) > 0:
                    nonzero += 1
            except Exception:
                pass
        out.append(f"fallback token accounts: {nonzero} non-zero SPL accounts; DeFi/Jupiter positions may be missing")
    except Exception:
        pass
    return out

def is_symbol_candidate(line: str) -> bool:
    if line in {'Show all', 'Validators', 'Orca', 'Kamino', 'Wallet', 'Value'}:
        return False
    if is_money(line) or PCT_RE.fullmatch(line):
        return False
    if re.fullmatch(r"[0-9][0-9,]*(?:\.[0-9]+)?", line):
        return False
    return bool(re.fullmatch(r"[$A-Za-z][A-Za-z0-9.$_-]{1,15}", line))


def jupiter_holding_rows(lines: list[str], limit: int = 7) -> list[str]:
    try:
        i = lines.index('Value') + 1
    except ValueError:
        return []
    rows: list[str] = []
    j = i
    while j < len(lines) - 2 and len(rows) < limit:
        symbol = lines[j]
        if symbol in {'Validators', 'Orca', 'Kamino', 'Show all'}:
            break
        if not is_symbol_candidate(symbol):
            j += 1
            continue
        next_j = len(lines)
        for k in range(j + 2, min(len(lines), j + 14)):
            if is_symbol_candidate(lines[k]):
                next_j = k
                break
        window = lines[j + 1:next_j]
        money_values = [x for x in window if is_money(x)]
        if money_values:
            value = money_values[-1]
            change = next((x for x in window if PCT_RE.fullmatch(x)), None)
            rows.append(f"{symbol}: {value}{f' ({change})' if change else ''}")
        j = next_j if next_j < len(lines) else j + 1
    return rows

def format_jupiter_item(text: str, address: str | None = None) -> list[str]:
    lines = clean_lines(text)
    out: list[str] = []
    def value_after(marker: str) -> str | None:
        try:
            i = lines.index(marker)
        except ValueError:
            return None
        for nxt in lines[i + 1:i + 5]:
            if is_money(nxt) or 'SOL' in nxt or PCT_RE.search(nxt):
                return nxt
        return None
    net = value_after('Net Worth')
    sol = None
    change = None
    try:
        i = lines.index('Net Worth')
        for nxt in lines[i + 1:i + 8]:
            if 'SOL' in nxt and not sol:
                sol = nxt
            if 'since' in nxt or PCT_RE.search(nxt):
                change = nxt
    except ValueError:
        pass
    if net:
        out.append(f"net worth: {net}{f', {sol}' if sol else ''}{f', {change}' if change else ''}")
    pnl = value_after('Holdings PnL')
    claim = value_after('Claimable')
    if pnl:
        out.append(f"holdings PnL: {pnl}")
    if claim:
        out.append(f"claimable: {claim}")
    sections = pairs_after(lines, 'Holdings', {'Wallet', 'Asset Balance Price/24hΔ PnL (all time)'}, limit=7)
    if sections:
        out.append('sections: ' + '; '.join(sections))
    tokens = jupiter_holding_rows(lines, limit=7)
    if tokens:
        out.append('holdings: ' + '; '.join(tokens))
    # DeFi sections after validators/orca/kamino are often more useful than tiny wallet tokens.
    defi = []
    for marker in ('Validators', 'Orca', 'Kamino', 'Jupiter DAO'):
        val = value_after(marker)
        if val:
            defi.append(f"{marker}: {val}")
    if defi:
        out.append('defi/staked: ' + '; '.join(defi[:6]))
    page_text = '\n'.join(lines).lower()
    if 'verification required to view your portfolio' in page_text or 'checking that you are a human' in page_text:
        return [
            'Jupiter page opened, but portfolio data is hidden by human verification',
            'needs one-time verification in the persistent Camofox profile; not using partial RPC fallback as portfolio review',
        ]
    if not out or not any(line.startswith('net worth:') for line in out):
        return [
            'Jupiter page opened, but Net Worth / token list / DeFi blocks were not visible in the browser snapshot',
            'Solana total is excluded from aggregate until Jupiter portfolio data is visible',
        ]
    return out or useful_lines(text, limit=6)


def jupiter_has_readable_net_worth(text: str) -> bool:
    return any(line.startswith('net worth:') for line in format_jupiter_item(text))


def split_named_money_rows(text: str) -> list[tuple[str, float, str]]:
    rows: list[tuple[str, float, str]] = []
    for part in re.split(r";\s*", text):
        if ':' not in part:
            continue
        name, raw = [x.strip() for x in part.split(':', 1)]
        # DeBank accessibility text can merge the previous value into the next name:
        # "$216.98 Hyperliquid: $97". Keep the human protocol/token name only.
        name = re.sub(r"^[-+]?<?\$[0-9][0-9,]*(?:\.[0-9]+)?[KMB]?\s+", "", name, flags=re.I).strip()
        m = re.search(r"[-+]?<?\$[0-9][0-9,]*(?:\.[0-9]+)?[KMB]?", raw, re.I)
        if name and m:
            rows.append((name, money_value(m.group(0)), m.group(0)))
    return rows


def unique_named_rows(rows: list[tuple[str, float, str]]) -> list[tuple[str, float, str]]:
    out: list[tuple[str, float, str]] = []
    seen: set[str] = set()
    for name, value, raw in rows:
        key = name.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append((name, value, raw))
    return out


def generate_action_recommendations(items: list[dict[str, Any]], totals: list[tuple[str, float, str]], known_total: float) -> list[str]:
    actions: list[str] = []
    if not known_total:
        return [
            "- сначала восстановить сбор данных: без читаемого net worth нельзя делать выводы по ребалансу",
            "- после восстановления проверить, не скрыты ли DeFi/staked/claimable позиции за browser verification",
        ]

    top_wallet = max(totals, key=lambda x: x[1]) if totals else None
    if top_wallet:
        top_pct = top_wallet[1] / known_total * 100
        if top_pct >= 70:
            actions.append(f"- проверить концентрацию: {top_wallet[0]} занимает {top_pct:.1f}% портфеля; если это не целевой основной счёт/стратегия, задать лимит и план снижения")
        elif top_pct >= 55:
            actions.append(f"- держать под наблюдением концентрацию: крупнейший кошелёк {top_wallet[0]} = {top_pct:.1f}%; это ещё терпимо, но нужен понятный тезис")

    protocol_rows: list[tuple[str, float, str]] = []
    token_rows: list[tuple[str, float, str]] = []
    chain_rows: list[tuple[str, float, str]] = []
    liquid_rows: list[tuple[str, float, str]] = []
    claimable_total = 0.0
    negative_total_lines: list[str] = []

    for item in items:
        if item["kind"] == "evm":
            summary = summarize_debank_item(item.get("text", ""))
            for row in summary.get("protocols") or []:
                protocol_rows.extend(split_named_money_rows(row))
            for row in summary.get("tokens") or []:
                token_rows.extend(split_named_money_rows(row))
            for row in summary.get("chains") or []:
                chain_rows.extend(split_named_money_rows(row))
            if summary.get("walletTotal"):
                liquid_rows.append(("EVM liquid", money_value(summary["walletTotal"]), summary["walletTotal"]))
            total_line = f"{summary.get('total') or ''} {summary.get('change') or ''}".strip()
            if '-' in total_line and summary.get('change'):
                negative_total_lines.append(total_line)
        else:
            for line in format_jupiter_item(item.get("text", ""), item.get("address")):
                if line.startswith('claimable:'):
                    claimable_total += money_value(line)
                elif line.startswith('defi/staked:') or line.startswith('sections:'):
                    protocol_rows.extend(split_named_money_rows(line.split(':', 1)[1]))
                elif line.startswith('holdings:'):
                    token_rows.extend(split_named_money_rows(line.split(':', 1)[1]))
                elif line.startswith('net worth:') and '-' in line:
                    negative_total_lines.append(line)

    if claimable_total >= 5:
        actions.append(f"- забрать/реинвестировать claimable: сейчас видно около {format_usd(claimable_total)}; это конкретное действие, а не просто наблюдение")

    protocol_token_symbols = {'USDC', 'USDT', 'DAI', 'USDE', 'SUSDE', 'ETH', 'WETH', 'BTC', 'WBTC', 'CBBTC', 'SOL', 'HYPE'}
    top_protocols = unique_named_rows(sorted([row for row in protocol_rows if row[0].upper() not in protocol_token_symbols], key=lambda x: x[1], reverse=True))[:5]
    if top_protocols:
        biggest_name, biggest_value, biggest_raw = top_protocols[0]
        biggest_pct = biggest_value / known_total * 100
        if biggest_pct >= 20:
            actions.append(f"- отдельно проверить главный риск-протокол: {biggest_name} = {biggest_raw} ({biggest_pct:.1f}% портфеля); тезис, риск смарт-контракта/биржи, условия выхода")
        review = '; '.join(f"{name} {raw}" for name, _value, raw in top_protocols[:4])
        actions.append(f"- пройти DeFi/staked позиции по списку: {review}; для каждой оставить только если понятны доходность, локап и риск")

    stable_like = [row for row in token_rows if row[0].upper() in {'USDC', 'USDT', 'DAI', 'USDE', 'SUSDE', 'USD'}]
    stable_total = sum(v for _n, v, _raw in stable_like)
    liquid_total = sum(v for _n, v, _raw in liquid_rows) + stable_total
    if liquid_total:
        liquid_pct = liquid_total / known_total * 100
        if liquid_pct < 10:
            actions.append(f"- ликвидная/стейбл-часть выглядит низкой: видно около {format_usd(liquid_total)} ({liquid_pct:.1f}%); решить, нужен ли буфер 10–20%")
        elif liquid_pct > 35:
            actions.append(f"- стейблы/ликвидная часть заметные: около {format_usd(liquid_total)} ({liquid_pct:.1f}%); если это не dry powder, определить куда и когда размещать")

    top_chains = sorted(chain_rows, key=lambda x: x[1], reverse=True)[:3]
    if top_chains:
        chain_text = '; '.join(f"{name} {raw}" for name, _value, raw in top_chains)
        actions.append(f"- проверить сетевую концентрацию и газ/выводы: основные сети сейчас {chain_text}")

    core_or_stable_symbols = {'USDC', 'USDT', 'DAI', 'USDE', 'SUSDE', 'ETH', 'WETH', 'BTC', 'WBTC', 'CBBTC', 'SOL'}
    small_tokens = unique_named_rows([row for row in token_rows if row[0].upper() not in core_or_stable_symbols and 0 < row[1] < max(25, known_total * 0.003)])
    if len(small_tokens) >= 3:
        sample = ', '.join(name for name, _value, _raw in small_tokens[:5])
        actions.append(f"- почистить мелкие позиции без тезиса: например {sample}; оставить только airdrop/venture-тезисы, остальное объединить")

    if negative_total_lines:
        actions.append("- не реагировать продажей только на минус за период; сначала разделить: рынок просел, фарм/локап просел или сломался конкретный тезис")

    actions.append("- итоговое решение на неделю: выбрать 1–2 конкретных действия из списка выше, остальные оставить как наблюдение до следующего отчёта")

    # Keep the cron message readable in Telegram.
    deduped: list[str] = []
    seen: set[str] = set()
    for action in actions:
        key = re.sub(r"\$[0-9][0-9,]*(?:\.[0-9]+)?", "$N", action.lower())
        if key not in seen:
            seen.add(key)
            deduped.append(action)
    return deduped[:7]


def build_message(items: list[dict[str, Any]], reason: str) -> str:
    totals: list[tuple[str, float, str]] = []
    for idx, item in enumerate(items, 1):
        if item["kind"] == "evm":
            summary = summarize_debank_item(item.get("text", ""))
            if summary.get("total"):
                totals.append((f"EVM {idx}", money_value(summary["total"]), summary["total"]))
        else:
            for line in format_jupiter_item(item.get("text", ""), item.get("address")):
                m = re.search(r"net worth:\s+(\$[0-9][0-9,]*(?:\.[0-9]+)?[KMB]?)", line, re.I)
                if m:
                    totals.append((f"Solana {idx}", money_value(m.group(1)), m.group(1)))
                    break

    known_total = sum(value for _, value, _ in totals)
    lines = ["Портфолио: browser-check через DeBank/Jupiter увидел изменение, стоит посмотреть.", ""]
    if reason == "bootstrap":
        lines[0] = "Портфолио: browser-check через DeBank/Jupiter инициализирован."

    if totals:
        lines.append(f"Итого по кошелькам, где удалось извлечь net worth: {format_usd(known_total)}")
        for label, value, raw in sorted(totals, key=lambda x: x[1], reverse=True):
            pct = (value / known_total * 100) if known_total else 0
            lines.append(f"- {label}: {raw} ({pct:.1f}%)")
        if len(totals) < len(items):
            lines.append("- часть источников не дала читаемый net worth, поэтому общий итог неполный")
        lines.append("")

    for item in items:
        label = "EVM / DeBank" if item["kind"] == "evm" else "Solana / Jupiter"
        lines.append(label)
        picked = format_debank_item(item.get("text", "")) if item["kind"] == "evm" else format_jupiter_item(item.get("text", ""), item.get("address"))
        if picked:
            for line in picked[:7]:
                lines.append(f"- {line}")
        else:
            title = item.get("title") or "страница открылась, но полезный текст не извлечён"
            lines.append(f"- {title}")
        lines.append("")

    sources_count = len(items)
    wallet_word = "кошельку" if sources_count == 1 else "кошелькам"
    concentration = (max((v for _, v, _ in totals), default=0) / known_total) if known_total else 0
    if not totals:
        assessment = "недостаточно данных: страницы открылись, но net worth не извлечён"
    elif concentration >= 0.75:
        assessment = "есть сильная концентрация в одном кошельке/сегменте; это не обязательно плохо, но требует осознанного тезиса"
    elif concentration >= 0.60:
        assessment = "есть заметная концентрация в одном кошельке/сегменте; это нормально только если так и задумано стратегией"
    else:
        assessment = "по распределению между читаемыми кошельками выглядит без критического перекоса"
    lines.extend([
        f"Оценка: {assessment}.",
        "Учёт: browser-visible DeBank/Jupiter остаются основой; RPC/native fallback не подменяет DeFi/staked/claimable данные, спорные строки надо держать audit-only.",
        f"Конкретные действия по всем {wallet_word}:",
    ])
    lines.extend(generate_action_recommendations(items, totals, known_total))
    return "\n".join(lines).strip()


async def main_async(args: argparse.Namespace) -> dict[str, Any]:
    state = read_json(args.state, {})
    ensure_chro()
    entries = read_addresses()
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    for entry in entries:
        url = f"https://debank.com/profile/{entry['address']}" if entry["kind"] == "evm" else f"https://jup.ag/portfolio/{entry['address']}"
        try:
            if entry["kind"] == "sol":
                title, text = await open_solana_chromium_text(entry["address"], args.wait)
                if not jupiter_has_readable_net_worth(text):
                    # Jupiter can render the application shell before portfolio rows are
                    # available in DOM text. Retry once with a fresh, longer Chromium read
                    # before excluding Solana/Jupiter from the aggregate report.
                    title_retry, text_retry = await open_solana_chromium_text(entry["address"], max(args.wait * 2, args.wait + 15, 30))
                    if jupiter_has_readable_net_worth(text_retry) or len(text_retry) > len(text):
                        title, text = title_retry, text_retry
                if os.environ.get("PORTFOLIO_DEBUG_DUMP_SOL"):
                    Path(os.environ["PORTFOLIO_DEBUG_DUMP_SOL"]).write_text(text, encoding="utf-8")
            else:
                title, text = await open_and_text(url, args.wait)
            items.append({"kind": entry["kind"], "keyHash": short_hash(entry["key"]), "title": title, "text": text, "address": entry["address"]})
        except Exception as exc:
            errors.append(f"{entry['kind']}:{type(exc).__name__}")
    fingerprint = source_fingerprint(items)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    first = not state.get("lastFingerprint")
    changed = bool(state.get("lastFingerprint") and state.get("lastFingerprint") != fingerprint)
    send = changed or (first and args.send_bootstrap)
    reason = "bootstrap" if first else "changed" if changed else "no_material_change"
    message = build_message(items, reason) if send else ""
    next_state = {
        "version": 1,
        "lastRunAt": now,
        "lastFingerprint": fingerprint,
        "lastSentAt": now if send else state.get("lastSentAt"),
        "lastDecision": {"sent": send, "reason": reason, "sources": len(items), "errorsCount": len(errors)},
    }
    if not args.dry_run:
        write_json(args.state, next_state)
    close_camofox_portfolio_group()
    return {
        "ok": True,
        "dryRun": args.dry_run,
        "checkedAt": now,
        "send": send,
        "reason": reason,
        "message": message,
        "sources": len(items),
        "errorsCount": len(errors),
        "privacy": "state stores only hashes, timestamps and decision metadata; no addresses, balances, raw page text, token amounts, totals, or percentages",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, default=STATE_PATH)
    parser.add_argument("--wait", type=int, default=18)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument("--message-only", action="store_true")
    parser.add_argument("--send-bootstrap", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = asyncio.run(main_async(args))
        if args.message_only:
            print(result.get("message") or "NO_REPLY")
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
