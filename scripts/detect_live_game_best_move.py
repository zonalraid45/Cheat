#!/usr/bin/env python3
import argparse
import os
import json
import time
import chess
import chess.engine
import requests

LICHESS_USER_GAMES_URL = "https://lichess.org/api/games/user/{username}"
LICHESS_TV_CHANNELS_URL = "https://lichess.org/api/tv/channels"

def fetch_ongoing_games(username: str) -> list[dict]:
    try:
        response = requests.get(
            LICHESS_USER_GAMES_URL.format(username=username),
            params={"ongoing": "true", "moves": "true"},
            headers={"Accept": "application/x-ndjson"},
            timeout=15,
        )
        response.raise_for_status()
        return [json.loads(line) for line in response.text.splitlines() if line.strip()]
    except Exception:
        return []

def get_fen(game: dict) -> str | None:
    initial_fen = game.get("initialFen", chess.STARTING_FEN)
    board = chess.Board(initial_fen) if initial_fen != "startpos" else chess.Board()
    moves = game.get("moves", "")
    if moves:
        for move in moves.split():
            try:
                board.push_san(move)
            except:
                break
    return board.fen()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", required=True)
    parser.add_argument("--stockfish-path", default="stockfish")
    args = parser.parse_args()

    print(f"Monitoring games for {args.username}... (Ctrl+C to stop)")
    
    # Track last move seen for each game ID to avoid repeat output
    last_seen_state = {} 

    with chess.engine.SimpleEngine.popen_uci(args.stockfish_path) as engine:
        while True:
            games = fetch_ongoing_games(args.username)
            
            for game in games:
                game_id = game.get("id")
                fen = get_fen(game)
                if not fen: continue
                
                board = chess.Board(fen)
                # Create a unique key for this game state (ID + current FEN)
                current_state_key = f"{game_id}_{fen}"

                # Only analyze and print if the board state has changed
                if last_seen_state.get(game_id) != current_state_key:
                    white_name = game.get("players", {}).get("white", {}).get("user", {}).get("name", "White")
                    black_name = game.get("players", {}).get("black", {}).get("user", {}).get("name", "Black")
                    
                    info = engine.analyse(board, chess.engine.Limit(time=0.8), multipv=2)
                    
                    move_num = board.fullmove_number
                    prefix = f"{move_num}. " if board.turn == chess.WHITE else f"{move_num}... "
                    
                    best_move = "N/A"
                    alt_move = "N/A"
                    
                    if isinstance(info, list) and len(info) > 0:
                        best_move = f"{prefix}{board.san(info[0]['pv'][0])}"
                        if len(info) > 1:
                            alt_move = f"{prefix}{board.san(info[1]['pv'][0])}"

                    print(f"\n[NEW MOVE] {white_name} vs {black_name} ({game_id})")
                    print(f"Best move:   {best_move}")
                    print(f"Alternative: {alt_move}")
                    
                    last_seen_state[game_id] = current_state_key

            time.sleep(5) # Check for new moves every 5 seconds

if __name__ == "__main__":
    main()
