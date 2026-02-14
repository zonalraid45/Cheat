#!/usr/bin/env python3
import argparse
import os
import json

import chess
import chess.engine
import requests

LICHESS_USER_GAMES_URL = "https://lichess.org/api/games/user/{username}"
LICHESS_TV_CHANNELS_URL = "https://lichess.org/api/tv/channels"


def fetch_ongoing_games(username: str) -> list[dict]:
    """Fetch ongoing games for a user from Lichess public API."""
    response = requests.get(
        LICHESS_USER_GAMES_URL.format(username=username),
        params={
            "ongoing": "true",
            "max": 10,
            "clocks": "true",
            "evals": "false",
            "opening": "false",
            "moves": "false",
            "pgnInJson": "false",
        },
        headers={"Accept": "application/x-ndjson"},
        timeout=25,
    )
    response.raise_for_status()

    games: list[dict] = []
    for line in response.text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            games.append(json.loads(line))
        except Exception:
            continue
    return games


def fallback_tv_match(username: str) -> list[dict]:
    """Fallback to featured TV games when direct ongoing feed has no analyzable games."""
    response = requests.get(
        LICHESS_TV_CHANNELS_URL,
        headers={"Accept": "application/json"},
        timeout=20,
    )
    response.raise_for_status()
    channels = response.json()

    matches: list[dict] = []
    for _, channel_data in channels.items():
        if not isinstance(channel_data, dict):
            continue

        white = channel_data.get("white", {})
        black = channel_data.get("black", {})
        white_name = (white.get("name") or "").lower()
        black_name = (black.get("name") or "").lower()

        if username.lower() not in {white_name, black_name}:
            continue

        game = {
            "id": channel_data.get("gameId"),
            "players": {
                "white": {"user": {"name": white.get("name", "White")}},
                "black": {"user": {"name": black.get("name", "Black")}},
            },
            "fen": channel_data.get("fen"),
        }
        matches.append(game)
    return matches


def get_fen(game: dict) -> str | None:
    return game.get("fen") or game.get("lastFen")


def get_player_name(game: dict, color: str, default: str) -> str:
    players = game.get("players", {})
    side = players.get(color, {})
    user = side.get("user", {})
    name = user.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return default


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect live games and suggest best move.")
    parser.add_argument("--username", required=True, help="Lichess username to inspect")
    parser.add_argument("--stockfish-path", default=os.getenv("STOCKFISH_PATH", "stockfish"))
    parser.add_argument("--analysis-time", type=float, default=0.8)
    args = parser.parse_args()

    username = args.username.strip()
    if not username:
        raise SystemExit("Username cannot be empty")

    print(f"Detected account ({username})")
    print("Detecting games....")

    games = fetch_ongoing_games(username)
    analyzable_games = [game for game in games if get_fen(game)]

    if not analyzable_games:
        analyzable_games = fallback_tv_match(username)

    if not analyzable_games:
        print(f"No live game found for {username}.")
        return 0

    with chess.engine.SimpleEngine.popen_uci(args.stockfish_path) as engine:
        for game in analyzable_games:
            fen = get_fen(game)
            if not fen:
                continue

            game_id = game.get("id") or game.get("gameId") or "unknown"
            white_name = get_player_name(game, "white", "White")
            black_name = get_player_name(game, "black", "Black")

            try:
                board = chess.Board(fen)
            except ValueError:
                continue

            info = engine.analyse(
                board,
                chess.engine.Limit(time=args.analysis_time),
                multipv=2,
            )

            best_move = "N/A"
            alt_move = "N/A"

            if isinstance(info, list) and info:
                pv0 = info[0].get("pv", [])
                pv1 = info[1].get("pv", []) if len(info) > 1 else []
                if pv0:
                    best_move = pv0[0].uci()
                if pv1:
                    alt_move = pv1[0].uci()
            elif isinstance(info, dict):
                pv = info.get("pv", [])
                if pv:
                    best_move = pv[0].uci()

            print(f"{white_name} vs {black_name} {game_id} detected")
            print(f"Best move - {best_move}")
            print(f"Alternative move - {alt_move}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
