#!/usr/bin/env python3
import argparse
import os
import json
import time
import chess
import chess.engine
import requests

LICHESS_ONGOING_URL = "https://lichess.org/api/games/user/{username}"

def fetch_ongoing_games(username: str) -> list[dict]:
    try:
        headers = {"Accept": "application/x-ndjson"}
        params = {"ongoing": "true", "moves": "true"}
        response = requests.get(
            LICHESS_ONGOING_URL.format(username=username),
            params=params, headers=headers, timeout=10
        )
        if response.status_code == 429:
            time.sleep(60)
            return []
        return [json.loads(line) for line in response.text.strip().split('\n') if line]
    except Exception:
        return []

def get_current_board(game: dict) -> chess.Board:
    initial_fen = game.get("initialFen", chess.STARTING_FEN)
    board = chess.Board(initial_fen) if initial_fen != "startpos" else chess.Board()
    moves = game.get("moves", "")
    if moves:
        for move in moves.split():
            try:
                board.push_san(move)
            except:
                try: board.push_uci(move)
                except: continue
    return board

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", required=True)
    parser.add_argument("--stockfish-path", default="stockfish")
    args = parser.parse_args()

    target_user = args.username.lower()
    last_processed_state = {} 

    print(f"Monitoring turns for: {args.username} (0.2s analysis)")

    with chess.engine.SimpleEngine.popen_uci(args.stockfish_path) as engine:
        start_time = time.time()
        while (time.time() - start_time) < 21600: # 6 Hour loop
            games = fetch_ongoing_games(args.username)
            
            for game in games:
                game_id = game.get("id")
                board = get_current_board(game)
                
                # Determine which color the typed username is playing
                white_player = game.get("players", {}).get("white", {}).get("user", {}).get("name", "").lower()
                user_color = chess.WHITE if white_player == target_user else chess.BLACK
                
                # ONLY proceed if it is currently the user's turn
                if board.turn == user_color:
                    move_count = len(board.move_stack)
                    state_key = f"{game_id}_{move_count}"

                    if last_processed_state.get(game_id) != state_key:
                        # Fast 0.2s analysis
                        info = engine.analyse(board, chess.engine.Limit(time=0.2), multipv=2)
                        
                        move_num = board.fullmove_number
                        prefix = f"{move_num}. " if board.turn == chess.WHITE else f"{move_num}... "
                        
                        best_move = "N/A"
                        alt_move = "N/A"
                        if info:
                            best_move = f"{prefix}{board.san(info[0]['pv'][0])}"
                            if len(info) > 1:
                                alt_move = f"{prefix}{board.san(info[1]['pv'][0])}"

                        print(f"\n[YOUR TURN] Game: {game_id}")
                        print(f"Best Move:   {best_move}")
                        print(f"Alternative: {alt_move}")
                        
                        last_processed_state[game_id] = state_key
                else:
                    # Opponent's turn - clear state tracker to be ready for next move
                    if game_id in last_processed_state:
                        last_processed_state[game_id] = "waiting"

            time.sleep(2) # Faster polling (2 seconds) to catch turns quickly

if __name__ == "__main__":
    main()
