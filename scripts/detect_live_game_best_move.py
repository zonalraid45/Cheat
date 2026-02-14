#!/usr/bin/env python3
import argparse
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
            time.sleep(30)
            return []
            
        lines = response.text.strip().split('\n')
        games = [json.loads(line) for line in lines if line]
        # ONLY return games that are currently in progress
        return [g for g in games if g.get("status") == "started"]
    except Exception:
        return []

def get_current_board(game: dict) -> chess.Board:
    initial_fen = game.get("initialFen", chess.STARTING_FEN)
    # Handle "startpos" string vs actual FEN
    board = chess.Board(initial_fen) if initial_fen != "startpos" else chess.Board()
    moves = game.get("moves", "")
    if moves:
        for move in moves.split():
            try:
                # Try SAN first, then UCI
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

    print(f"--- Monitoring ACTIVE Games for: {args.username} ---")

    with chess.engine.SimpleEngine.popen_uci(args.stockfish_path) as engine:
        while True:
            games = fetch_ongoing_games(args.username)
            
            # Keep track of active IDs to clean up the cache later
            active_game_ids = []

            for game in games:
                game_id = game.get("id")
                active_game_ids.append(game_id)
                board = get_current_board(game)
                
                # Identify players
                players = game.get("players", {})
                white_name = players.get("white", {}).get("user", {}).get("name", "Unknown")
                black_name = players.get("black", {}).get("user", {}).get("name", "Unknown")
                
                # Determine your color
                is_white = white_name.lower() == target_user
                user_color = chess.WHITE if is_white else chess.BLACK
                opponent_name = black_name if is_white else white_name

                # Verification: Is it actually your turn based on the board?
                is_your_turn = (board.turn == user_color)
                
                move_count = len(board.move_stack)
                state_key = f"{game_id}_{move_count}"

                if is_your_turn:
                    # Only analyze if this is a NEW move state for your turn
                    if last_processed_state.get(game_id) != state_key:
                        # Analysis time 0.8s (range 0.5s - 1.0s)
                        info = engine.analyse(board, chess.engine.Limit(time=0.8), multipv=2)
                        
                        full_move = board.fullmove_number
                        # Proper notation for White (7.) vs Black (7...)
                        prefix = f"{full_move}. " if board.turn == chess.WHITE else f"{full_move}... "
                        
                        best_move = "N/A"
                        alt_move = "N/A"
                        if info:
                            best_move = f"{prefix}{board.san(info[0]['pv'][0])}"
                            if len(info) > 1:
                                alt_move = f"{prefix}{board.san(info[1]['pv'][0])}"

                        print(f"\n[!] YOUR TURN vs {opponent_name}")
                        print(f"Move Number: {full_move}")
                        print(f"Best:        {best_move}")
                        print(f"Alternative: {alt_move}")
                        print(f"Link: https://lichess.org/{game_id}")
                        
                        last_processed_state[game_id] = state_key
                else:
                    # It's the opponent's turn. 
                    # If we weren't already waiting, show status.
                    if last_processed_state.get(game_id) != "waiting":
                        print(f"[*] {opponent_name} is thinking in game {game_id}...")
                        last_processed_state[game_id] = "waiting"

            # Clean up cache for games that are no longer in the 'ongoing' list
            keys_to_remove = [k for k in last_processed_state if k not in active_game_ids and "_" not in k]
            for k in keys_to_remove:
                last_processed_state.pop(k, None)

            time.sleep(1.5) 

if __name__ == "__main__":
    main()
