#!/usr/bin/env python3
import argparse
import os
import json
import time
import chess
import chess.engine
import requests

# Endpoints
LICHESS_ONGOING_URL = "https://lichess.org/api/games/user/{username}"

def fetch_ongoing_games(username: str) -> list[dict]:
    """Fetch games and handle potential API quirks."""
    try:
        # Use headers to force JSON format (NDJSON)
        headers = {"Accept": "application/x-ndjson"}
        params = {
            "ongoing": "true",
            "moves": "true",
            "max": 5
        }
        response = requests.get(
            LICHESS_ONGOING_URL.format(username=username),
            params=params,
            headers=headers,
            timeout=15
        )
        
        if response.status_code == 429:
            print("Rate limited by Lichess. Waiting...")
            time.sleep(60)
            return []

        response.raise_for_status()
        
        # Parse NDJSON (line by line JSON)
        games = []
        for line in response.text.strip().split('\n'):
            if line:
                try:
                    games.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return games
    except Exception as e:
        print(f"Error fetching games: {e}")
        return []

def get_current_board(game: dict) -> chess.Board:
    """Reconstructs the board from the moves string."""
    initial_fen = game.get("initialFen")
    if not initial_fen or initial_fen == "startpos":
        board = chess.Board()
    else:
        board = chess.Board(initial_fen)
        
    moves = game.get("moves", "")
    if moves:
        for move in moves.split():
            try:
                board.push_san(move)
            except ValueError:
                # If SAN fails, try UCI
                try:
                    board.push_uci(move)
                except:
                    continue
    return board

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", required=True)
    parser.add_argument("--stockfish-path", default="stockfish")
    args = parser.parse_args()

    print(f"Starting 6-hour monitor for user: {args.username}")
    
    last_move_count = {} # game_id -> number of moves made

    with chess.engine.SimpleEngine.popen_uci(args.stockfish_path) as engine:
        start_time = time.time()
        # 6 hours = 21600 seconds
        while (time.time() - start_time) < 21600:
            games = fetch_ongoing_games(args.username)
            
            if not games:
                # Optional: print a dot to show it's still running
                pass

            for game in games:
                game_id = game.get("id")
                moves_str = game.get("moves", "")
                move_list = moves_str.split()
                move_count = len(move_list)

                # Only output if the move count has changed (a new move was made)
                if game_id not in last_move_count or last_move_count[game_id] != move_count:
                    board = get_current_board(game)
                    
                    # Analyze
                    info = engine.analyse(board, chess.engine.Limit(time=0.8), multipv=2)
                    
                    move_num = board.fullmove_number
                    prefix = f"{move_num}. " if board.turn == chess.WHITE else f"{move_num}... "
                    
                    best_move = "N/A"
                    alt_move = "N/A"
                    
                    if info:
                        if len(info) > 0 and "pv" in info[0]:
                            best_move = f"{prefix}{board.san(info[0]['pv'][0])}"
                        if len(info) > 1 and "pv" in info[1]:
                            alt_move = f"{prefix}{board.san(info[1]['pv'][0])}"

                    print(f"\n--- NEW STATE: {game_id} ---")
                    print(f"White: {game.get('players',{}).get('white',{}).get('user',{}).get('name')}")
                    print(f"Black: {game.get('players',{}).get('black',{}).get('user',{}).get('name')}")
                    print(f"Best Move:       {best_move}")
                    print(f"Alternative:     {alt_move}")
                    
                    last_move_count[game_id] = move_count

            time.sleep(5) # Poll every 5 seconds

if __name__ == "__main__":
    main()
