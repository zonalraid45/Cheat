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
        # 'ongoing=true' filters for games currently in progress
        params = {"ongoing": "true", "moves": "true"}
        response = requests.get(
            LICHESS_ONGOING_URL.format(username=username),
            params=params, headers=headers, timeout=10
        )
        if response.status_code == 429:
            time.sleep(30)
            return []
            
        # Parse and filter for only 'started' games to avoid resigned/timed-out ghosts
        games = [json.loads(line) for line in response.text.strip().split('\n') if line]
        return [g for g in games if g.get("status") == "started"]
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

    print(f"--- Monitoring Live Games for: {args.username} ---")

    with chess.engine.SimpleEngine.popen_uci(args.stockfish_path) as engine:
        while True:
            games = fetch_ongoing_games(args.username)
            
            for game in games:
                game_id = game.get("id")
                board = get_current_board(game)
                
                # Identify players and opponent
                players = game.get("players", {})
                white_info = players.get("white", {}).get("user", {})
                black_info = players.get("black", {}).get("user", {})
                
                white_name = white_info.get("name", "Unknown")
                black_name = black_info.get("name", "Unknown")
                
                if white_name.lower() == target_user:
                    user_color = chess.WHITE
                    opponent = black_name
                else:
                    user_color = chess.BLACK
                    opponent = white_name

                # Tracking the state by Game ID + Move Count
                move_count = len(board.move_stack)
                state_key = f"{game_id}_{move_count}"

                # Only analyze if it is YOUR TURN and we haven't shown this move yet
                if board.turn == user_color:
                    if last_processed_state.get(game_id) != state_key:
                        # Analysis set to 0.8s for balance of speed and depth
                        info = engine.analyse(board, chess.engine.Limit(time=0.8), multipv=2)
                        
                        move_num = board.fullmove_number
                        prefix = f"{move_num}. " if board.turn == chess.WHITE else f"{move_num}... "
                        
                        best_move = "N/A"
                        alt_move = "N/A"
                        if info:
                            best_move = f"{prefix}{board.san(info[0]['pv'][0])}"
                            if len(info) > 1:
                                alt_move = f"{prefix}{board.san(info[1]['pv'][0])}"

                        print(f"\n[!] YOUR TURN vs {opponent}")
                        print(f"Game Link: https://lichess.org/{game_id}")
                        print(f"Best Move:    {best_move}")
                        print(f"Alternative: {alt_move}")
                        print("-" * 30)
                        
                        last_processed_state[game_id] = state_key
                else:
                    # If it's the opponent's turn, we just wait and clear the 'last move' 
                    # cache for this game so we are ready the moment they move.
                    if last_processed_state.get(game_id) != "waiting":
                        print(f"[*] Waiting for {opponent} to move in {game_id}...")
                        last_processed_state[game_id] = "waiting"

            time.sleep(1.5) # Fast polling to catch moves immediately

if __name__ == "__main__":
    main()
