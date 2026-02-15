#!/usr/bin/env python3

import argparse
import os
import json
import time
import threading
import requests
import chess
import chess.engine

EVENT_STREAM = "https://lichess.org/api/stream/event"
BOT_GAME_STREAM = "https://lichess.org/api/bot/game/stream/{}"
BOARD_GAME_STREAM = "https://lichess.org/api/board/game/stream/{}"
ACCOUNT_INFO = "https://lichess.org/api/account"
ACTIVE_GAMES = "https://lichess.org/api/account/playing"
TOKEN_TEST = "https://lichess.org/api/token/test"
GAME_EXPORT = "https://lichess.org/game/export/{}"


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def get_account_info(token):
    try:
        response = requests.get(ACCOUNT_INFO, headers=auth_headers(token), timeout=15)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict):
            return data
    except Exception as exc:
        print(f"[!] Could not fetch account info from token: {exc}")
    return {}


def get_account_username(token):
    return get_account_info(token).get("username")


def get_active_game_ids(token):
    game_ids = []
    try:
        response = requests.get(ACTIVE_GAMES, headers=auth_headers(token), timeout=15)
        response.raise_for_status()
        data = response.json()
        for game in data.get("nowPlaying", []):
            game_id = game.get("gameId")
            if game_id:
                game_ids.append(game_id)
    except Exception as exc:
        print(f"[!] Could not fetch active games: {exc}")
    return game_ids


def get_token_scopes(token):
    try:
        response = requests.get(TOKEN_TEST, headers=auth_headers(token), timeout=15)
        if response.status_code == 404:
            return []
        response.raise_for_status()
        data = response.json()
        scopes = data.get("scopes")
        if isinstance(scopes, list):
            return sorted(scope for scope in scopes if isinstance(scope, str))
    except Exception as exc:
        print(f"[!] Could not fetch token scopes: {exc}")
    return []


def stream_events(token):
    headers = auth_headers(token)
    with requests.get(EVENT_STREAM, headers=headers, stream=True) as r:
        for line in r.iter_lines():
            if not line:
                continue
            try:
                data = json.loads(line)
                if isinstance(data, dict):
                    yield data
            except Exception:
                continue


def player_name(player):
    if not isinstance(player, dict):
        return "Unknown"
    return player.get("name") or player.get("id") or "Unknown"


def format_eval(score, pov_color):
    if score is None:
        return ""

    pov_score = score.pov(pov_color)
    mate_score = pov_score.mate()
    if mate_score is not None:
        return f"M{mate_score:+d}"

    centipawns = pov_score.score()
    if centipawns is None:
        return ""

    return f"{centipawns / 100:+.1f}"


def stream_game_lines(game_id, headers, is_bot_account, attempts=12, delay_seconds=1.5):
    # Prefer the account-appropriate stream, but also try the other endpoint.
    # Some game types are only available on one of these APIs.
    if is_bot_account:
        endpoints = [
            ("bot", BOT_GAME_STREAM.format(game_id)),
            ("board", BOARD_GAME_STREAM.format(game_id)),
        ]
    else:
        endpoints = [
            ("board", BOARD_GAME_STREAM.format(game_id)),
            ("bot", BOT_GAME_STREAM.format(game_id)),
        ]

    last_failures = []
    for attempt in range(1, attempts + 1):
        last_failures = []
        for endpoint_name, endpoint in endpoints:
            try:
                response = requests.get(endpoint, headers=headers, stream=True, timeout=60)
                if response.status_code == 200:
                    return response.iter_lines(), response, None

                status = response.status_code
                body = response.text.strip().replace("\n", " ")
                if len(body) > 160:
                    body = body[:157] + "..."
                last_failures.append(f"{endpoint_name}:{status} ({body or 'no body'})")
                response.close()
            except Exception as exc:
                last_failures.append(f"{endpoint_name}:error ({exc})")
                continue

        if attempt < attempts:
            time.sleep(delay_seconds)

    return None, None, "; ".join(last_failures)


def fetch_game_export(game_id, headers):
    response = requests.get(
        GAME_EXPORT.format(game_id),
        headers={**headers, "Accept": "application/json"},
        params={"moves": "true", "pgnInJson": "true", "clocks": "true"},
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("Unexpected export payload")
    return data


def extract_names_from_export(payload):
    players = payload.get("players", {}) if isinstance(payload, dict) else {}

    def from_color(color):
        side = players.get(color, {}) if isinstance(players, dict) else {}
        user = side.get("user", {}) if isinstance(side, dict) else {}
        return user.get("name") or side.get("name") or "Unknown"

    return from_color("white"), from_color("black")


def analyse_and_print_position(engine, board, username, white, black, game_id):
    if not white or not black:
        return

    is_white = white.lower() == username.lower()
    user_color = chess.WHITE if is_white else chess.BLACK
    opponent = black if is_white else white
    current_move = board.fullmove_number

    if board.turn == user_color:
        if board.is_game_over():
            print(f"\n[!] Game over vs {opponent} (Game: {game_id})")
            return

        info = engine.analyse(
            board,
            chess.engine.Limit(time=0.8),
            multipv=2
        )

        if not info or "pv" not in info[0] or not info[0]["pv"]:
            print(f"\n[!] Your turn vs {opponent} (Game: {game_id})")
            print(f"Current move: {current_move}")
            print("No engine move available for this position.")
            print(f"Link: https://lichess.org/{game_id}")
            return

        prefix = (
            f"{current_move}. "
            if board.turn == chess.WHITE
            else f"{current_move}... "
        )

        best = prefix + board.san(info[0]["pv"][0])
        best_eval = format_eval(info[0].get("score"), user_color)
        alt = "N/A"
        alt_eval = ""
        if len(info) > 1 and info[1].get("pv"):
            alt = prefix + board.san(info[1]["pv"][0])
            alt_eval = format_eval(info[1].get("score"), user_color)

        print(f"\n[!] YOUR TURN (Game: {game_id})")
        print(f"Opponent:    {opponent}")
        print(f"Current move:{current_move}")
        print(f"STOCKFISH:   {best:<12} {best_eval}".rstrip())
        print(f"ALTERNATIVE: {alt:<12} {alt_eval}".rstrip())
        print(f"Link: https://lichess.org/{game_id}")

    else:
        print(f"[*] Waiting for opponent to move (Game: {game_id})")
        print(f"Opponent:    {opponent}")


def fallback_poll_game(game_id, token, username, engine_path, interval_seconds=1.0):
    headers = auth_headers(token)
    board = chess.Board()
    last_position_key = None
    white = None
    black = None

    print(f"[*] Falling back to export polling for game {game_id}.")

    with chess.engine.SimpleEngine.popen_uci(engine_path) as engine:
        while True:
            try:
                payload = fetch_game_export(game_id, headers)
            except Exception as exc:
                print(f"[!] Polling error for {game_id}: {exc}")
                time.sleep(interval_seconds)
                continue

            white, black = extract_names_from_export(payload)

            moves = payload.get("moves", "")
            board.reset()
            if moves:
                for move in moves.split():
                    board.push_uci(move)

            position_key = (len(board.move_stack), board.turn)
            if position_key != last_position_key:
                last_position_key = position_key
                analyse_and_print_position(engine, board, username, white, black, game_id)

            status = payload.get("status")
            if isinstance(status, str) and status.lower() not in {"started", "created"}:
                print(f"[!] Polling ended, game status: {status} (Game: {game_id})")
                break

            time.sleep(interval_seconds)


def stream_game(game_id, token, username, engine_path, is_bot_account):
    headers = auth_headers(token)
    board = chess.Board()
    white = None
    black = None
    last_position_key = None

    try:
        line_iter, response, failure_reason = stream_game_lines(game_id, headers, is_bot_account)
        if not line_iter:
            print(f"[!] Could not open game stream for {game_id}.")
            if failure_reason:
                print(f"    Last API replies: {failure_reason}")

                failure_lower = failure_reason.lower()
                if "401" in failure_reason or "403" in failure_reason:
                    print("    Token is likely missing required scopes (board:play and/or bot:play).")
                elif "cannot be played with the board api" in failure_lower:
                    print("    This game is not streamable through Board API for this token/account.")
                elif "cannot be played with the bot api" in failure_lower:
                    print("    This game is not streamable through Bot API for this token/account.")
                else:
                    print("    Could not determine a valid stream endpoint for this game.")
            return

        with chess.engine.SimpleEngine.popen_uci(engine_path) as engine:
            with response:
                for line in line_iter:
                    if not line:
                        continue

                    try:
                        event = json.loads(line)
                    except Exception:
                        continue

                    if not isinstance(event, dict):
                        continue

                    event_type = event.get("type")
                    if not event_type:
                        continue

                    if event_type == "gameFull":
                        board.reset()
                        moves = event.get("state", {}).get("moves", "")
                        if moves:
                            for move in moves.split():
                                board.push_uci(move)

                        white = player_name(event.get("white"))
                        black = player_name(event.get("black"))

                    elif event_type == "gameState":
                        board.reset()
                        moves = event.get("moves", "")
                        if moves:
                            for move in moves.split():
                                board.push_uci(move)

                    else:
                        continue

                    if not white or not black:
                        continue

                    # Avoid duplicate prints for identical positions.
                    position_key = (len(board.move_stack), board.turn)
                    if position_key == last_position_key:
                        continue
                    last_position_key = position_key

                    analyse_and_print_position(engine, board, username, white, black, game_id)

    except Exception as exc:
        print(f"[!] Stream error in game {game_id}: {exc}")

    if not is_bot_account:
        fallback_poll_game(game_id, token, username, engine_path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", help="Lichess username (auto-detected from token if omitted)")
    parser.add_argument("--stockfish-path", default="stockfish")
    args = parser.parse_args()

    token = os.getenv("LICHESS_TOKEN")
    if not token:
        print("Missing LICHESS_TOKEN environment variable.")
        return

    account = get_account_info(token)
    username = args.username or account.get("username")
    if not username:
        print("Missing username. Provide --username or use a token with account scope.")
        return

    is_bot_account = account.get("title") == "BOT"
    account_kind = "BOT" if is_bot_account else "HUMAN"

    print(f"--- REAL-TIME STREAM MONITORING: {username} ({account_kind}) ---")

    scopes = get_token_scopes(token)
    if scopes:
        print(f"[*] Token scopes: {', '.join(scopes)}")
        if is_bot_account and "bot:play" not in scopes:
            print("[!] Warning: bot account detected, but bot:play scope is missing.")
        if not is_bot_account and "board:play" not in scopes:
            print("[!] Warning: human account detected, but board:play scope is missing.")

    started_games = set()

    # Detect already-live games when the script starts.
    for game_id in get_active_game_ids(token):
        started_games.add(game_id)
        print(f"\n[+] Live Game Detected: {game_id}")
        threading.Thread(
            target=stream_game,
            args=(game_id, token, username, args.stockfish_path, is_bot_account),
            daemon=True
        ).start()

    for event in stream_events(token):
        if event.get("type") == "gameStart":
            game_id = event["game"]["id"]
            if game_id in started_games:
                continue
            started_games.add(game_id)
            print(f"\n[+] Game Started: {game_id}")

            threading.Thread(
                target=stream_game,
                args=(game_id, token, username, args.stockfish_path, is_bot_account),
                daemon=True
            ).start()


if __name__ == "__main__":
    main()
