#!/usr/bin/env python3

import argparse
import os
import json
import threading
import requests
import chess
import chess.engine

EVENT_STREAM = "https://lichess.org/api/stream/event"
GAME_STREAM = "https://lichess.org/api/bot/game/stream/{}"


def stream_events(token):
    headers = {"Authorization": f"Bearer {token}"}
    with requests.get(EVENT_STREAM, headers=headers, stream=True) as r:
        for line in r.iter_lines():
            if line:
                yield json.loads(line)


def stream_game(game_id, token, username, engine_path):
    headers = {"Authorization": f"Bearer {token}"}
    board = chess.Board()
    white = None
    black = None

    with chess.engine.SimpleEngine.popen_uci(engine_path) as engine:
        with requests.get(GAME_STREAM.format(game_id), headers=headers, stream=True) as r:
            for line in r.iter_lines():
                if not line:
                    continue

                event = json.loads(line)

                if event["type"] == "gameFull":
                    board.reset()
                    moves = event["state"]["moves"]
                    if moves:
                        for move in moves.split():
                            board.push_uci(move)

                    white = event["white"]["name"]
                    black = event["black"]["name"]

                elif event["type"] == "gameState":
                    board.reset()
                    moves = event["moves"]
                    if moves:
                        for move in moves.split():
                            board.push_uci(move)

                else:
                    continue

                if not white or not black:
                    continue

                is_white = white.lower() == username.lower()
                user_color = chess.WHITE if is_white else chess.BLACK
                opponent = black if is_white else white

                move_count = len(board.move_stack)
                full_move = (move_count // 2) + 1

                if board.turn == user_color:
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

                else:
                    print(f"[*] Waiting for {opponent} in {game_id} (Move {full_move})")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", required=True)
    parser.add_argument("--stockfish-path", default="stockfish")
    args = parser.parse_args()

    token = os.getenv("LICHESS_TOKEN")
    if not token:
        print("Missing LICHESS_TOKEN environment variable.")
        return

    print(f"--- REAL-TIME STREAM MONITORING: {args.username} ---")

    for event in stream_events(token):
        if event["type"] == "gameStart":
            game_id = event["game"]["id"]
            print(f"\n[+] Game Started: {game_id}")

            threading.Thread(
                target=stream_game,
                args=(game_id, token, args.username, args.stockfish_path),
                daemon=True
            ).start()


if __name__ == "__main__":
    main()
