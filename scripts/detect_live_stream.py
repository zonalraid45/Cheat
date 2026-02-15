#!/usr/bin/env python3

import argparse
import os
import json
import threading
import requests
import chess
import chess.engine

EVENT_STREAM = "https://lichess.org/api/stream/event"
BOT_GAME_STREAM = "https://lichess.org/api/bot/game/stream/{}"
BOARD_GAME_STREAM = "https://lichess.org/api/board/game/stream/{}"
ACCOUNT_INFO = "https://lichess.org/api/account"
ACTIVE_GAMES = "https://lichess.org/api/account/playing"


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def get_account_username(token):
    try:
        response = requests.get(ACCOUNT_INFO, headers=auth_headers(token), timeout=15)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict):
            return data.get("username")
    except Exception as exc:
        print(f"[!] Could not fetch username from token: {exc}")
    return None


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


def stream_events(token):
    headers = auth_headers(token)
    with requests.get(EVENT_STREAM, headers=headers, stream=True, timeout=60) as r:
        r.raise_for_status()
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


def stream_game_lines(game_id, headers):
    endpoints = [BOT_GAME_STREAM.format(game_id), BOARD_GAME_STREAM.format(game_id)]
    for endpoint in endpoints:
        try:
            response = requests.get(endpoint, headers=headers, stream=True, timeout=60)
            if response.status_code == 200:
                return response.iter_lines(), response
            response.close()
        except Exception:
            continue
    return None, None


def stream_game(game_id, token, username, engine_path):
    headers = auth_headers(token)
    board = chess.Board()
    white = None
    black = None
    last_position_key = None

    try:
        with chess.engine.SimpleEngine.popen_uci(engine_path) as engine:
            line_iter, response = stream_game_lines(game_id, headers)
            if not line_iter:
                print(f"[!] Could not open game stream for {game_id}. Token may need board/bot scope.")
                return

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

                    is_white = white.lower() == username.lower()
                    user_color = chess.WHITE if is_white else chess.BLACK
                    opponent = black if is_white else white
                    current_move = board.fullmove_number

                    if board.turn == user_color:
                        if board.is_game_over():
                            print(f"\n[!] Game over vs {opponent} (Game: {game_id})")
                            continue

                        info = engine.analyse(
                            board,
                            chess.engine.Limit(time=0.8),
                            multipv=2
                        )

                        if not info or "pv" not in info[0] or not info[0]["pv"]:
                            print(f"\n[!] YOUR TURN (Game: {game_id})")
                            print(f"Opponent:     {opponent}")
                            print(f"Current move: {current_move}")
                            print("No engine move available for this position.")
                            print(f"Link: https://lichess.org/{game_id}")
                            continue

                        prefix = (
                            f"{current_move}. "
                            if board.turn == chess.WHITE
                            else f"{current_move}... "
                        )

                        best = prefix + board.san(info[0]["pv"][0])
                        alt = "N/A"
                        if len(info) > 1 and info[1].get("pv"):
                            alt = prefix + board.san(info[1]["pv"][0])

                        print(f"\n[!] YOUR TURN (Game: {game_id})")
                        print(f"Opponent:     {opponent}")
                        print(f"Current move: {current_move}")
                        print(f"STOCKFISH:    {best}")
                        print(f"ALTERNATIVE:  {alt}")
                        print(f"Link: https://lichess.org/{game_id}")

                    else:
                        print(f"\n[*] Waiting for opponent to move (Game: {game_id})")
                        print(f"Opponent:     {opponent}")

    except Exception as exc:
        print(f"[!] Stream error in game {game_id}: {exc}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", help="Lichess username (auto-detected from token if omitted)")
    parser.add_argument("--stockfish-path", default="stockfish")
    args = parser.parse_args()

    token = os.getenv("LICHESS_TOKEN")
    if not token:
        print("Missing LICHESS_TOKEN environment variable.")
        return

    username = args.username or get_account_username(token)
    if not username:
        print("Missing username. Provide --username or use a token with account scope.")
        return

    print(f"--- REAL-TIME STREAM MONITORING: {username} ---")

    started_games = set()

    # Detect already-live games when the script starts.
    for game_id in get_active_game_ids(token):
        started_games.add(game_id)
        print(f"\n[+] Live Game Detected: {game_id}")
        threading.Thread(
            target=stream_game,
            args=(game_id, token, username, args.stockfish_path),
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
                args=(game_id, token, username, args.stockfish_path),
                daemon=True
            ).start()


if __name__ == "__main__":
    main()
