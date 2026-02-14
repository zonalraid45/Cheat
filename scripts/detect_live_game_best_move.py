#!/usr/bin/env python3

import argparse
import json
import time
import requests
import chess
import chess.engine

LICHESS_ONGOING_URL = "https://lichess.org/api/games/user/{username}"


def fetch_ongoing_games(username: str):
    headers = {
        "Accept": "application/x-ndjson",
        "Cache-Control": "no-cache"
    }
    params = {
        "ongoing": "true",
        "moves": "true"
    }

    try:
        r = requests.get(
            LICHESS_ONGOING_URL.format(username=username),
            headers=headers,
            params=params,
            timeout=10
        )

        if r.status_code == 429:
            print("[!] Rate limited. Sleeping 15s...")
            time.sleep(15)
            return []

        lines = r.text.strip().split("\n")
        games = [json.loads(line) for line in lines if line]

        return [g for g in games if g.get("status") == "started"]

    except Exception:
        return []


def build_board_from_game(game: dict) -> chess.Board:
    initial_fen = game.get("initialFen", chess.STARTING_FEN)

    if initial_fen == "startpos":
        board = chess.Board()
    else:
        board = chess.Board(initial_fen)

    moves = game.get("moves", "")
    if moves:
        for move in moves.split():
            try:
                board.push_uci(move)
            except Exception:
                continue

    return board


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", required=True)
    parser.add_argument("--stockfish-path", default="stockfish")
    args = parser.parse_args()

    target_user = args.username.lower()
    last_state = {}

    print(f"--- ACTIVE MONITORING: {args.username} ---")

    with chess.engine.SimpleEngine.popen_uci(args.stockfish_path) as engine:

        while True:
            games = fetch_ongoing_games(args.username)
            active_ids = []

            for game in games:
                game_id = game.get("id")
                active_ids.append(game_id)

                board = build_board_from_game(game)
                move_count = len(board.move_stack)

                # Identify players
                players = game.get("players", {})
                white_name = players.get("white", {}).get("user", {}).get("name", "Unknown")
                black_name = players.get("black", {}).get("user", {}).get("name", "Unknown")

                is_white = white_name.lower() == target_user
                user_color = chess.WHITE if is_white else chess.BLACK
                opponent = black_name if is_white else white_name

                # Determine turn using board
                is_your_turn = (board.turn == user_color)

                state_key = f"{game_id}_{move_count}"

                if is_your_turn:
                    if last_state.get(game_id) != state_key:

                        info = engine.analyse(
                            board,
                            chess.engine.Limit(time=0.8),
                            multipv=2
                        )

                        full_move = (move_count // 2) + 1
                        prefix = (
                            f"{full_move}. "
                            if board.turn == chess.WHITE
                            else f"{full_move}... "
                        )

                        best = "N/A"
                        alt = "N/A"

                        if info:
                            best = prefix + board.san(info[0]["pv"][0])
                            if len(info) > 1:
                                alt = prefix + board.san(info[1]["pv"][0])

                        print(f"\n[!] YOUR TURN vs {opponent} (Game: {game_id})")
                        print(f"Move:        {full_move}")
                        print(f"STOCKFISH:   {best}")
                        print(f"ALTERNATIVE: {alt}")
                        print(f"Link: https://lichess.org/{game_id}")

                        last_state[game_id] = state_key

                else:
                    if last_state.get(game_id) != "waiting":
                        print(f"[*] Waiting for {opponent} in {game_id} (Move { (move_count // 2) + 1 })")
                        last_state[game_id] = "waiting"

            # Clean cache for finished games
            for gid in list(last_state.keys()):
                if gid not in active_ids:
                    last_state.pop(gid, None)

            time.sleep(1.5)


if __name__ == "__main__":
    main()
