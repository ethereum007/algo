#!/usr/bin/env python3
"""Local platform for the Rupeezy Indian algo trading skill."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent
if (WORKSPACE / "plugins" / "indian-algo-trading").exists():
    SKILL_ROOT = WORKSPACE
else:
    PRIMARY_SKILL_ROOT = WORKSPACE / "ethereum007-algo"
    FALLBACK_SKILL_ROOT = WORKSPACE / "algo_ai_skill"
    SKILL_ROOT = PRIMARY_SKILL_ROOT if PRIMARY_SKILL_ROOT.exists() else FALLBACK_SKILL_ROOT
SKILL_DIR = SKILL_ROOT / "plugins" / "indian-algo-trading" / "skills" / "indian-algo-trading"
SCAFFOLD_SCRIPT = SKILL_DIR / "scripts" / "scaffold_strategy.py"
VALIDATE_SCRIPT = SKILL_DIR / "scripts" / "validate_strategy.py"
REFERENCES_DIR = SKILL_DIR / "references"
GENERATED_DIR = ROOT / "generated_strategies"
STATIC_DIR = ROOT / "static"
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1d&interval=1m"
INDEX_SYMBOLS = {
    "NIFTY": "^NSEI",
    "NIFTY50": "^NSEI",
    "NIFTY 50": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "NIFTYBANK": "^NSEBANK",
    "NIFTY BANK": "^NSEBANK",
    "SENSEX": "^BSESN",
}


class PlatformError(Exception):
    """Expected request or platform error."""

    def __init__(self, message: str, status: HTTPStatus = HTTPStatus.BAD_REQUEST):
        super().__init__(message)
        self.status = status


def clean_name(value: str) -> str:
    """Keep generated project names filesystem-safe and predictable."""
    cleaned = "".join(char if char.isalnum() or char in "-_" else "_" for char in value.strip())
    cleaned = cleaned.strip("_-").lower()
    if not cleaned:
        raise PlatformError("Strategy name is required.")
    return cleaned[:64]


def require_skill_repo() -> None:
    if not SCAFFOLD_SCRIPT.exists() or not VALIDATE_SCRIPT.exists():
        raise PlatformError(
            "The algo_ai_skill repository is missing. Clone RupeezyTech/algo_ai_skill beside this platform.",
            HTTPStatus.INTERNAL_SERVER_ERROR,
        )


def run_python(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=str(cwd),
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )


def normalize_market_symbol(symbol: str) -> str:
    raw = symbol.strip().upper()
    if not raw:
        raise PlatformError("Symbol is required.")
    if raw in INDEX_SYMBOLS:
        return INDEX_SYMBOLS[raw]
    if raw.startswith("^") or raw.endswith(".NS") or raw.endswith(".BO"):
        return raw
    return f"{raw}.NS"


def fetch_yahoo_quote(symbol: str) -> dict:
    yahoo_symbol = normalize_market_symbol(symbol)
    url = YAHOO_CHART_URL.format(symbol=quote(yahoo_symbol, safe="^"))
    request = Request(url, headers={"User-Agent": "AlgoAIPlatform/1.0"})
    try:
        with urlopen(request, timeout=12) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise PlatformError(f"Could not fetch market data for {symbol}: {exc}", HTTPStatus.BAD_GATEWAY) from exc

    result = (payload.get("chart", {}).get("result") or [None])[0]
    if not result:
        error = payload.get("chart", {}).get("error") or {}
        raise PlatformError(error.get("description") or f"No data returned for {symbol}.", HTTPStatus.BAD_GATEWAY)

    meta = result.get("meta", {})
    timestamps = result.get("timestamp") or []
    quote_data = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    close_values = quote_data.get("close") or []
    volume_values = quote_data.get("volume") or []
    candles = []

    for index, ts in enumerate(timestamps[-60:]):
        close = close_values[index + max(0, len(timestamps) - 60)] if close_values else None
        if close is None:
            continue
        volume = volume_values[index + max(0, len(timestamps) - 60)] if volume_values else None
        candles.append(
            {
                "time": datetime.fromtimestamp(ts, timezone.utc).isoformat(),
                "close": round(float(close), 2),
                "volume": int(volume or 0),
            }
        )

    current_price = meta.get("regularMarketPrice")
    previous_close = meta.get("previousClose")
    change = None
    change_pct = None
    if current_price is not None and previous_close:
        change = float(current_price) - float(previous_close)
        change_pct = (change / float(previous_close)) * 100

    return {
        "inputSymbol": symbol.strip().upper(),
        "providerSymbol": yahoo_symbol,
        "exchangeName": meta.get("exchangeName"),
        "currency": meta.get("currency", "INR"),
        "price": round(float(current_price), 2) if current_price is not None else None,
        "previousClose": round(float(previous_close), 2) if previous_close is not None else None,
        "change": round(change, 2) if change is not None else None,
        "changePct": round(change_pct, 2) if change_pct is not None else None,
        "marketState": meta.get("marketState"),
        "regularMarketTime": meta.get("regularMarketTime"),
        "dataDelay": meta.get("exchangeDataDelayedBy"),
        "candles": candles,
    }


def fetch_market_data(symbols: str) -> dict:
    requested = [symbol.strip() for symbol in symbols.split(",") if symbol.strip()]
    if not requested:
        requested = ["NIFTY", "RELIANCE", "HDFCBANK", "TCS"]
    if len(requested) > 12:
        raise PlatformError("Please request 12 symbols or fewer at a time.")

    quotes = []
    errors = []
    for symbol in requested:
        try:
            quotes.append(fetch_yahoo_quote(symbol))
        except PlatformError as exc:
            errors.append({"symbol": symbol, "error": str(exc)})

    return {
        "provider": "Yahoo Finance chart",
        "mode": "public delayed market data",
        "disclaimer": "For research and UI validation only. Broker-grade live trading should use Rupeezy/Vortex market data and WebSocket order updates.",
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
        "quotes": quotes,
        "errors": errors,
    }


def read_json_body(handler: SimpleHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0"))
    if length <= 0:
        return {}
    raw = handler.rfile.read(length).decode("utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PlatformError(f"Invalid JSON body: {exc}") from exc


def write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")


def build_strategy_readme(project_dir: Path, payload: dict) -> None:
    lines = [
        f"# {payload['display_name']}",
        "",
        "Generated by Algo AI Platform using RupeezyTech/algo_ai_skill.",
        "",
        "## Strategy Brief",
        f"- Asset class: {payload['asset_class']}",
        f"- Mode: {payload['mode']}",
        f"- Broker: {payload['broker']}",
        f"- Entry logic: {payload['entry_logic']}",
        f"- Exit logic: {payload['exit_logic']}",
        f"- Position sizing: {payload['position_sizing']}",
        f"- Schedule: {payload['schedule']}",
        "",
        "## Risk Limits",
        f"- Max loss per trade: {payload['risk_per_trade']}%",
        f"- Max daily loss: {payload['daily_loss']}%",
        f"- Max drawdown pause: {payload['max_drawdown']}%",
        f"- Max open positions: {payload['max_positions']}",
        "",
        "## Required Safety Review",
        "- Replace placeholder signal logic in `strategy.py` before live use.",
        "- Verify instrument lookup, tick size, DPR, margin checks, and stop-loss behavior with broker data.",
        "- Paper trade first. Backtests are not proof of future returns.",
    ]
    write_text(project_dir / "README.md", "\n".join(lines) + "\n")


def patch_config(project_dir: Path, payload: dict) -> None:
    config_path = project_dir / "config.py"
    content = config_path.read_text(encoding="utf-8")
    max_loss = max(1000, int(float(payload["capital"]) * float(payload["daily_loss"]) / 100))
    max_position = max(1000, int(float(payload["capital"]) * float(payload["risk_per_trade"]) / 100 * 8))
    replacements = {
        "max_loss_per_day: float = 5000.0": f"max_loss_per_day: float = {max_loss}.0",
        "max_position_value: float = 100000.0": f"max_position_value: float = {max_position}.0",
        "max_open_positions: int = 5": f"max_open_positions: int = {int(payload['max_positions'])}",
        'exchange: str = "NSE"': f'exchange: str = "{payload["exchange"]}"',
        'default_product: str = "DELIVERY"': f'default_product: str = "{payload["product"]}"',
        "initial_capital: float = 1000000.0": f"initial_capital: float = {float(payload['capital'])}",
    }
    for old, new in replacements.items():
        content = content.replace(old, new)
    write_text(config_path, content)


def strategy_overlay(payload: dict) -> str:
    return f'''"""
Strategy logic customized from the platform brief.

Keep this file signal-focused. Order execution should stay separate when broker
integration is added.
"""

import logging
from dataclasses import dataclass
from typing import Literal, Optional

from config import Config
from risk_manager import RiskManager

logger = logging.getLogger(__name__)


SignalSide = Literal["BUY", "SELL", "HOLD"]


@dataclass
class Signal:
    symbol: str
    side: SignalSide
    reason: str
    stop_loss_pct: float
    target_pct: float


class Strategy:
    """Platform-generated strategy shell for {payload['display_name']}."""

    def __init__(self, config: Config, risk_manager: RiskManager):
        self.config = config
        self.risk_manager = risk_manager
        self.positions = {{}}
        self.watchlist = {json.dumps(payload['symbols'])}
        self.entry_logic = {payload['entry_logic']!r}
        self.exit_logic = {payload['exit_logic']!r}

    def init(self):
        logger.info("Initializing strategy | symbols=%s | entry=%s", self.watchlist, self.entry_logic)

    def generate_signal(self, candle: dict) -> Signal:
        """Return a signal from broker-provided candle data.

        Expected candle keys: symbol, close, fast_ma, slow_ma, rsi, volume_ratio.
        Replace these placeholder indicator checks with your final research logic.
        """
        symbol = candle.get("symbol", self.watchlist[0])
        fast_ma = float(candle.get("fast_ma", 0))
        slow_ma = float(candle.get("slow_ma", 0))
        rsi = float(candle.get("rsi", 50))
        volume_ratio = float(candle.get("volume_ratio", 1))

        if fast_ma > slow_ma and rsi < 70 and volume_ratio >= 1:
            return Signal(symbol, "BUY", "Trend confirmation with acceptable RSI", 1.0, 2.0)
        if fast_ma < slow_ma or rsi > 78:
            return Signal(symbol, "SELL", "Momentum faded or RSI overheated", 1.0, 1.5)
        return Signal(symbol, "HOLD", "No clean edge", 1.0, 2.0)

    def next(self, tick):
        signal = self.generate_signal(tick if isinstance(tick, dict) else {{}})
        logger.info(
            "Signal | %s | %s | reason=%s | stop=%.2f%% | target=%.2f%%",
            signal.symbol,
            signal.side,
            signal.reason,
            signal.stop_loss_pct,
            signal.target_pct,
        )
        return signal

    def place_order(self, signal: Signal, price: float, quantity: int) -> Optional[dict]:
        """Risk-gated order request placeholder."""
        if signal.side == "HOLD":
            return None
        order = {{
            "symbol": signal.symbol,
            "side": signal.side,
            "quantity": quantity,
            "price": price,
            "stop_loss_pct": signal.stop_loss_pct,
            "target_pct": signal.target_pct,
        }}
        if not self.risk_manager.approve(order):
            logger.warning("Risk manager rejected order: %s", order)
            return None
        logger.info("Paper order approved: %s", order)
        return order

    def backtest(self):
        logger.info("Backtest shell ready. Add broker or CSV historical candles with realistic costs.")

    def run(self):
        logger.info("Live shell ready. Connect WebSocket before placing orders.")
'''


def generate_project(payload: dict) -> dict:
    require_skill_repo()
    GENERATED_DIR.mkdir(exist_ok=True)

    name = clean_name(payload.get("name", ""))
    project_dir = GENERATED_DIR / name
    if project_dir.exists():
        archive = GENERATED_DIR / f"{name}_{int(time.time())}"
        shutil.move(str(project_dir), str(archive))

    mode = "backtest" if payload.get("mode") == "Backtest" else "live"
    result = run_python([str(SCAFFOLD_SCRIPT), name, "--type", mode], GENERATED_DIR)
    if result.returncode != 0:
        raise PlatformError(result.stderr or result.stdout or "Scaffold failed.", HTTPStatus.INTERNAL_SERVER_ERROR)

    payload = {
        "display_name": payload.get("displayName") or name.replace("_", " ").title(),
        "asset_class": payload.get("assetClass", "Equity"),
        "mode": payload.get("mode", "Paper trading"),
        "broker": payload.get("broker", "Rupeezy / Vortex"),
        "exchange": payload.get("exchange", "NSE"),
        "product": payload.get("product", "INTRADAY"),
        "entry_logic": payload.get("entryLogic", "Moving average trend confirmation"),
        "exit_logic": payload.get("exitLogic", "Stop-loss, target, and time exit"),
        "position_sizing": payload.get("positionSizing", "Risk based"),
        "schedule": payload.get("schedule", "09:20-15:15 IST"),
        "risk_per_trade": float(payload.get("riskPerTrade", 1)),
        "daily_loss": float(payload.get("dailyLoss", 3)),
        "max_drawdown": float(payload.get("maxDrawdown", 10)),
        "max_positions": int(payload.get("maxPositions", 3)),
        "capital": float(payload.get("capital", 500000)),
        "symbols": [s.strip().upper() for s in payload.get("symbols", "RELIANCE,TCS,HDFCBANK").split(",") if s.strip()],
    }

    patch_config(project_dir, payload)
    write_text(project_dir / "strategy.py", strategy_overlay(payload))
    build_strategy_readme(project_dir, payload)
    validation = validate_path(project_dir)

    return {
        "name": name,
        "path": str(project_dir),
        "stdout": result.stdout,
        "stderr": result.stderr,
        "validation": validation,
        "files": list_project_files(project_dir),
    }


def validate_path(path: Path) -> dict:
    require_skill_repo()
    result = run_python([str(VALIDATE_SCRIPT), str(path)], ROOT)
    return {
        "exitCode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def list_project_files(project_dir: Path) -> list[dict]:
    files = []
    for path in sorted(project_dir.rglob("*")):
        if path.is_file():
            files.append(
                {
                    "name": path.relative_to(project_dir).as_posix(),
                    "size": path.stat().st_size,
                }
            )
    return files


def list_projects() -> list[dict]:
    GENERATED_DIR.mkdir(exist_ok=True)
    projects = []
    for path in sorted(GENERATED_DIR.iterdir()):
        if path.is_dir():
            projects.append({"name": path.name, "path": str(path), "files": list_project_files(path)})
    return projects


def list_references() -> list[dict]:
    refs = []
    if not REFERENCES_DIR.exists():
        return refs
    for path in sorted(REFERENCES_DIR.rglob("*.md")):
        rel = path.relative_to(REFERENCES_DIR).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        first_heading = next((line.lstrip("# ").strip() for line in text.splitlines() if line.startswith("#")), rel)
        refs.append({"id": rel, "title": first_heading, "bytes": path.stat().st_size})
    return refs


def get_reference(ref_id: str) -> dict:
    safe = Path(unquote(ref_id))
    if safe.is_absolute() or ".." in safe.parts:
        raise PlatformError("Invalid reference path.")
    path = REFERENCES_DIR / safe
    if not path.exists() or path.suffix != ".md":
        raise PlatformError("Reference not found.", HTTPStatus.NOT_FOUND)
    return {"id": safe.as_posix(), "content": path.read_text(encoding="utf-8", errors="replace")}


def project_file(project: str, file_name: str) -> dict:
    project_dir = GENERATED_DIR / clean_name(project)
    safe = Path(unquote(file_name))
    if safe.is_absolute() or ".." in safe.parts:
        raise PlatformError("Invalid file path.")
    path = project_dir / safe
    if not path.exists() or not path.is_file():
        raise PlatformError("File not found.", HTTPStatus.NOT_FOUND)
    return {"project": project, "file": safe.as_posix(), "content": path.read_text(encoding="utf-8", errors="replace")}


def zip_project(project: str) -> Path:
    project_dir = GENERATED_DIR / clean_name(project)
    if not project_dir.exists():
        raise PlatformError("Project not found.", HTTPStatus.NOT_FOUND)
    zip_path = GENERATED_DIR / f"{project_dir.name}.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in project_dir.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(project_dir.parent))
    return zip_path


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def log_message(self, format: str, *args) -> None:
        sys.stdout.write("%s - %s\n" % (self.address_string(), format % args))

    def json_response(self, payload: dict | list, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_error(self, exc: Exception) -> None:
        if isinstance(exc, PlatformError):
            self.json_response({"error": str(exc)}, exc.status)
            return
        self.json_response({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/health":
                self.json_response({"ok": True, "skillRepo": str(SKILL_ROOT), "generatedDir": str(GENERATED_DIR)})
            elif parsed.path == "/api/projects":
                self.json_response(list_projects())
            elif parsed.path == "/api/references":
                self.json_response(list_references())
            elif parsed.path == "/api/market-data":
                symbols = parse_qs(parsed.query).get("symbols", ["NIFTY,RELIANCE,HDFCBANK,TCS"])[0]
                self.json_response(fetch_market_data(symbols))
            elif parsed.path == "/api/reference":
                ref_id = parse_qs(parsed.query).get("id", [""])[0]
                self.json_response(get_reference(ref_id))
            elif parsed.path == "/api/file":
                query = parse_qs(parsed.query)
                self.json_response(project_file(query.get("project", [""])[0], query.get("file", [""])[0]))
            elif parsed.path == "/api/download":
                project = parse_qs(parsed.query).get("project", [""])[0]
                zip_path = zip_project(project)
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Disposition", f'attachment; filename="{zip_path.name}"')
                self.send_header("Content-Length", str(zip_path.stat().st_size))
                self.end_headers()
                with zip_path.open("rb") as handle:
                    shutil.copyfileobj(handle, self.wfile)
            else:
                super().do_GET()
        except Exception as exc:
            self.handle_error(exc)

    def do_POST(self) -> None:
        try:
            if self.path == "/api/generate":
                self.json_response(generate_project(read_json_body(self)))
            elif self.path == "/api/validate":
                payload = read_json_body(self)
                project = clean_name(payload.get("project", ""))
                self.json_response(validate_path(GENERATED_DIR / project))
            else:
                self.json_response({"error": "Not found"}, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self.handle_error(exc)


def main() -> int:
    GENERATED_DIR.mkdir(exist_ok=True)
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Algo AI Platform running at http://127.0.0.1:{port}")
    print(f"Using skill repo: {SKILL_ROOT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
