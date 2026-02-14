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


def build_board(initial_fen, moves_str):
    if initial_fen == "startpos":
        board = chess.Board()
    else:
        board = chess.Board(initial_fen)

    if moves_str:
        for move in moves_str.split():
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

    last_move_counts = {}      # store last known move count per game
    last_printed_state = {}    # avoid duplicate output

    print(f"--- ACTIVE MONITORING: {args.username} ---")

    with chess.engine.SimpleEngine.popen_uci(args.stockfish_path) as engine:

        while True:
            games = fetch_ongoing_games(args.username)
            active_ids = []

            for game in games:
                game_id = game.get("id")
                active_ids.append(game_id)

                initial_fen = game.get("initialFen", chess.STARTING_FEN)
                moves_str = game.get("moves", "")

                move_count = len(moves_str.split()) if moves_str else 0

                # 🔥 Ignore regression to 0 if we already saw moves
                if game_id in last_move_counts:
                    if move_count < last_move_counts[game_id]:
                        move_count = last_move_counts[game_id]
                        continue

                last_move_counts[game_id] = move_count

                board = build_board(initial_fen, moves_str)

                players = game.get("players", {})
                white_name = players.get("white", {}).get("user", {}).get("name", "")
                black_name = players.get("black", {}).get("user", {}).get("name", "")

                is_white = white_name.lower() == target_user
                user_color = chess.WHITE if is_white else chess.BLACK
                opponent = black_name if is_white else white_name

                is_your_turn = (board.turn == user_color)

                state_key = f"{game_id}_{move_count}"

                full_move = (move_count // 2) + 1

                if is_your_turn:
                    if last_printed_state.get(game_id) != state_key:

                        info = engine.analyse(
                            board,
                            chess.engine.Limit(time=0.8),
                            multipv=2
                        )

                        prefix = (
                            f"{full_move}. "
                            if board.turn == chess.WHITE
                            else f"{full_move}... "
                        )

                        best = prefix + board.san(info[0]["pv"][0])
                        alt = "N/A"
                        if len(info) > 1:
                            alt = prefix + board.san(info[1]["pv"][0])

                        print(f"\n[!] YOUR TURN vs {opponent} (Game: {game_id})")
                        print(f"Move:        {full_move}")
                        print(f"STOCKFISH:   {best}")
                        print(f"ALTERNATIVE: {alt}")
                        print(f"Link: https://lichess.org/{game_id}")

                        last_printed_state[game_id] = state_key

                else:
                    if last_printed_state.get(game_id) != "waiting_" + game_id:
                        print(f"[*] Waiting for {opponent} in {game_id} (Move {full_move})")
                        last_printed_state[game_id] = "waiting_" + game_id

            # cleanup finished games
            for gid in list(last_move_counts.keys()):
                if gid not in active_ids:
                    last_move_counts.pop(gid, None)
                    last_printed_state.pop(gid, None)

            time.sleep(1.5)


if __name__ == "__main__":
    main()
