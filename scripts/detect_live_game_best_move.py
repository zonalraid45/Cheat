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
        # Filter for ongoing only, and ensure moves are provided for board state
        params = {"ongoing": "true", "moves": "true"}
        response = requests.get(
            LICHESS_ONGOING_URL.format(username=username),
            params=params, headers=headers, timeout=10
        )
        if response.status_code == 429:
            print("Rate limited. Waiting 60s...")
            time.sleep(60)
            return []
        
        # Parse the NDJSON response
        games = [json.loads(line) for line in response.text.strip().split('\n') if line]
        
        # BRO FIX: Only keep games that are actually "started" (not resigned/finished)
        return [g for g in games if g.get("status") == "started"]
    except Exception as e:
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

    print(f"Monitoring LIVE games for: {args.username}")
    print("Analysis Time: 0.7s per move")

    with chess.engine.SimpleEngine.popen_uci(args.stockfish_path) as engine:
        start_time = time.time()
        while (time.time() - start_time) < 21600: # 6 Hour loop
            games = fetch_ongoing_games(args.username)
            
            for game in games:
                game_id = game.get("id")
                board = get_current_board(game)
                
                # Identify players
                players = game.get("players", {})
                white_name = players.get("white", {}).get("user", {}).get("name", "Unknown")
                black_name = players.get("black", {}).get("user", {}).get("name", "Unknown")
                
                # Determine user color and opponent name
                if white_name.lower() == target_user:
                    user_color = chess.WHITE
                    opponent = black_name
                else:
                    user_color = chess.BLACK
                    opponent = white_name
                
                # ONLY proceed if it is currently the user's turn
                if board.turn == user_color:
                    move_count = len(board.move_stack)
                    state_key = f"{game_id}_{move_count}"

                    if last_processed_state.get(game_id) != state_key:
                        # BRO FIX: Analysis time set to ~0.7s (between 0.5 and 1.0)
                        info = engine.analyse(board, chess.engine.Limit(time=0.7), multipv=2)
                        
                        move_num = board.fullmove_number
                        prefix = f"{move_num}. " if board.turn == chess.WHITE else f"{move_num}... "
                        
                        best_move = "N/A"
                        alt_move = "N/A"
                        if info:
                            best_move = f"{prefix}{board.san(info[0]['pv'][0])}"
                            if len(info) > 1:
                                alt_move = f"{prefix}{board.san(info[1]['pv'][0])}"

                        print(f"\n[YOUR TURN] vs {opponent} | Game: {game_id}")
                        print(f"Best Move:    {best_move}")
                        print(f"Alternative: {alt_move}")
                        
                        last_processed_state[game_id] = state_key
                else:
                    # Clear state tracker if it's the opponent's turn to be ready for your next move
                    if game_id in last_processed_state:
                        last_processed_state[game_id] = "waiting"

            time.sleep(2) 

if __name__ == "__main__":
    main()
