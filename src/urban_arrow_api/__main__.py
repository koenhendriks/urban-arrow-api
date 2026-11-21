"""Small CLI for exploring the API: ``urban-arrow login`` then ``urban-arrow status``."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
from datetime import date
from pathlib import Path
from typing import Any

import aiohttp

from . import ActivityPeriod, BikeSetting, Token, UrbanArrowClient
from .auth import create_login_request, exchange_code, extract_code
from .login import login_with_credentials

TOKEN_FILE = Path(os.environ.get("URBAN_ARROW_TOKEN_FILE", "~/.config/urban-arrow/token.json")).expanduser()


def _save(token: Token) -> None:
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(token.as_dict()))
    TOKEN_FILE.chmod(0o600)


def _dump(data: Any) -> None:
    print(json.dumps(data, indent=2, default=str))


async def _password_login(username: str) -> None:
    password = os.environ.get("URBAN_ARROW_PASSWORD") or getpass.getpass("Password: ")
    _save(await login_with_credentials(username, password))
    print(f"Saved token to {TOKEN_FILE}")


async def _browser_login() -> None:
    req = create_login_request()
    print("1. Open this URL in a browser and log in with your Urban Arrow account:\n")
    print(req.url)
    print(
        "\n2. After login the browser tries to open an 'urbanarrow://...' URL and fails."
        "\n   Copy that URL (DevTools > Network, or the address bar / error page) and paste it here."
    )
    redirect = input("\nRedirect URL or code: ")
    async with aiohttp.ClientSession() as session:
        token = await exchange_code(session, extract_code(redirect, req.state), req.code_verifier)
    _save(token)
    print(f"Saved token to {TOKEN_FILE}")


async def _run(args: argparse.Namespace) -> None:
    token = Token.from_dict(json.loads(TOKEN_FILE.read_text()))
    async with aiohttp.ClientSession() as session:
        client = UrbanArrowClient(session, token, on_token_update=_save)
        match args.command:
            case "bikes":
                _dump([b.raw for b in await client.get_bikes()])
            case "status":
                for summary in await client.get_bikes():
                    bike = await client.get_bike(summary.id)
                    print(f"== {bike.name} ({bike.id})")
                    _dump(bike.raw)
                    _dump((await client.get_telemetry(bike.id)).raw)
            case "activity":
                bike = await client.get_bike(args.bike_id)
                start = date.fromisoformat(args.start) if args.start else date.today().replace(day=1)
                _dump((await client.get_activity(bike, ActivityPeriod(args.period), start)).raw)
            case "notifications":
                _dump([n.raw for n in await client.get_notifications()])
            case "flash":
                await client.flash_lights(args.bike_id)
                print("ok")
            case "setting":
                await client.set_setting(args.bike_id, BikeSetting(args.setting), args.state == "on")
                print("ok")
            case "raw":
                _dump(await client._request(args.method.upper(), args.path))


def main() -> None:
    parser = argparse.ArgumentParser(prog="urban-arrow")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("login", help="Log in with email + password")
    p.add_argument("username")
    sub.add_parser("browser-login", help="Fallback: log in via browser and paste the redirect URL")
    sub.add_parser("bikes")
    sub.add_parser("status")
    sub.add_parser("notifications")
    p = sub.add_parser("activity")
    p.add_argument("bike_id")
    p.add_argument("--period", default="MONTH", choices=[p.value for p in ActivityPeriod])
    p.add_argument("--start", help="YYYY-MM-DD, defaults to first day of this month")
    p = sub.add_parser("flash")
    p.add_argument("bike_id")
    p = sub.add_parser("setting")
    p.add_argument("bike_id")
    p.add_argument("setting", choices=[s.value for s in BikeSetting])
    p.add_argument("state", choices=["on", "off"])
    p = sub.add_parser("raw", help="Call any endpoint path relative to /api/")
    p.add_argument("method")
    p.add_argument("path")
    args = parser.parse_args()
    match args.command:
        case "login":
            asyncio.run(_password_login(args.username))
        case "browser-login":
            asyncio.run(_browser_login())
        case _:
            asyncio.run(_run(args))


if __name__ == "__main__":
    main()
