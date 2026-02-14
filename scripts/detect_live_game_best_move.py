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
    # Cache to store the last move count we analyzed for each game
    last_analyzed_count = {} 

    print(f"--- ACTIVE MONITORING: {args.username} ---")

    with chess.engine.SimpleEngine.popen_uci(args.stockfish_path) as engine:
        while True:
            games = fetch_ongoing_games(args.username)
            active_games = [g for g in games if g.get("status") == "started"]
            
            if not active_games:
                print("No active games found. Waiting...", end="\r")

            for game in active_games:
                game_id = game.get("id")
                board = get_current_board(game)
                move_count = len(board.move_stack)
                
                # Identify players
                players = game.get("players", {})
                w_name = players.get("white", {}).get("user", {}).get("name", "Unknown")
                b_name = players.get("black", {}).get("user", {}).get("name", "Unknown")
                
                is_white = w_name.lower() == target_user
                user_color = chess.WHITE if is_white else chess.BLACK
                opponent = b_name if is_white else w_name

                # Logic: Is it YOUR turn according to the board state?
                if board.turn == user_color:
                    # Only analyze if we haven't analyzed this specific move count yet
                    if last_analyzed_count.get(game_id) != move_count:
                        # Analysis time set to 0.8s
                        info = engine.analyse(board, chess.engine.Limit(time=0.8), multipv=2)
                        
                        full_move = board.fullmove_number
                        prefix = f"{full_move}. " if board.turn == chess.WHITE else f"{full_move}... "
                        
                        best_move = "N/A"
                        alt_move = "N/A"
                        if info:
                            best_move = f"{prefix}{board.san(info[0]['pv'][0])}"
                            if len(info) > 1:
                                alt_move = f"{prefix}{board.san(info[1]['pv'][0])}"

                        print(f"\n[!] YOUR TURN vs {opponent} (Game: {game_id})")
                        print(f"Current Move: {full_move}")
                        print(f"STOCKFISH:   {best_move}")
                        print(f"ALTERNATIVE: {alt_move}")
                        print(f"Link: https://lichess.org/{game_id}")
                        
                        last_analyzed_count[game_id] = move_count
                else:
                    # It's the opponent's turn
                    if last_analyzed_count.get(game_id) != "waiting":
                        print(f"[*] Waiting for {opponent} in {game_id} (Move {board.fullmove_number})")
                        last_analyzed_count[game_id] = "waiting"

            time.sleep(1.0) # Faster polling (1 second)

if __name__ == "__main__":
    main()
