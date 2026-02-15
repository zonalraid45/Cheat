#!/usr/bin/env python3

import argparse
import os
import json
import time
import threading
import requests
import chess
import chess.engine

EVENT_STREAM = "https://lichess.org/api/stream/event"
BOT_GAME_STREAM = "https://lichess.org/api/bot/game/stream/{}"
BOARD_GAME_STREAM = "https://lichess.org/api/board/game/stream/{}"
ACCOUNT_INFO = "https://lichess.org/api/account"
ACTIVE_GAMES = "https://lichess.org/api/account/playing"
TOKEN_TEST = "https://lichess.org/api/token/test"


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def get_account_info(token):
    try:
        response = requests.get(ACCOUNT_INFO, headers=auth_headers(token), timeout=15)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict):
            return data
    except Exception as exc:
        print(f"[!] DEBUG: Could not fetch account info: {exc}")
    return {}


def get_active_game_ids(token):
    game_ids = []
    try:
        response = requests.get(ACTIVE_GAMES, headers=auth_headers(token), timeout=15)
        response.raise_for_status()
        data = response.json()
        for game in data.get("nowPlaying", []):
            game_id = game.get("gameId")
            if game_id:
                game_ids.append(game_id)
    except Exception as exc:
        print(f"[!] DEBUG: Could not fetch active games: {exc}")
    return game_ids


def get_token_scopes(token):
    try:
        response = requests.get(TOKEN_TEST, headers=auth_headers(token), timeout=15)
        if response.status_code == 404:
            return []
        response.raise_for_status()
        data = response.json()
        return data.get("scopes", [])
    except Exception as exc:
        print(f"[!] DEBUG: Could not fetch token scopes: {exc}")
    return []


def stream_events(token):
    headers = auth_headers(token)
    print("[*] DEBUG: Starting event stream...")
    with requests.get(EVENT_STREAM, headers=headers, stream=True) as r:
        for line in r.iter_lines():
            if not line:
                continue
            try:
                data = json.loads(line)
                yield data
            except Exception as exc:
                print(f"[!] DEBUG: Event stream JSON error: {exc}")
                continue


def format_eval(score, pov_color):
    if score is None: return ""
    pov_score = score.pov(pov_color)
    mate_score = pov_score.mate()
    if mate_score is not None: return f"M{mate_score:+d}"
    centipawns = pov_score.score()
    return f"{centipawns / 100:+.1f}" if centipawns is not None else ""


def stream_game_lines(game_id, headers, is_bot_account, attempts=12, delay_seconds=1.0):
    endpoints = [
        ("board", BOARD_GAME_STREAM.format(game_id)),
        ("bot", BOT_GAME_STREAM.format(game_id)),
    ]
    if is_bot_account:
        endpoints.reverse()

    last_failures = []
    for attempt in range(1, attempts + 1):
        for name, endpoint in endpoints:
            try:
                print(f"[*] DEBUG: Attempting {name} stream (Attempt {attempt})...")
                response = requests.get(endpoint, headers=headers, stream=True, timeout=60)
                if response.status_code == 200:
                    return response.iter_lines(), response, None
                last_failures.append(f"{name}:{response.status_code}")
                response.close()
            except Exception as exc:
                last_failures.append(f"{name}:err({exc})")
        time.sleep(delay_seconds)
    return None, None, "; ".join(last_failures)


def stream_game(game_id, token, username, engine_path, is_bot_account):
    headers = auth_headers(token)
    board = chess.Board()
    white, black = None, None
    game_speed = "rapid"  # Default
    last_position_key = None

    try:
        line_iter, response, failure_reason = stream_game_lines(game_id, headers, is_bot_account)
        if not line_iter:
            print(f"[!] DEBUG: Game {game_id} stream failed. Reason: {failure_reason}")
            return

        with chess.engine.SimpleEngine.popen_uci(engine_path) as engine:
            print(f"[*] DEBUG: Engine loaded for game {game_id}")
            with response:
                for line in line_iter:
                    if not line: continue
                    try:
                        event = json.loads(line)
                    except: continue

                    event_type = event.get("type")
                    if event_type == "gameFull":
                        game_speed = event.get("speed", "rapid")
                        print(f"[*] DEBUG: Game Speed Detected: {game_speed}")
                        
                        board.reset()
                        moves = event.get("state", {}).get("moves", "")
                        for move in moves.split(): board.push_uci(move)
                        
                        white = event.get("white", {}).get("name") or event.get("white", {}).get("id")
                        black = event.get("black", {}).get("name") or event.get("black", {}).get("id")

                    elif event_type == "gameState":
                        board.reset()
                        moves = event.get("moves", "")
                        for move in moves.split(): board.push_uci(move)
                    else:
                        continue

                    # Avoid duplicate processing
                    pos_key = (len(board.move_stack), board.turn)
                    if pos_key == last_position_key: continue
                    last_position_key = pos_key

                    is_white = str(white).lower() == username.lower()
                    user_color = chess.WHITE if is_white else chess.BLACK
                    opponent = black if is_white else white

                    if board.turn == user_color and not board.is_game_over():
                        # DYNAMIC TIMING: Blitz/Bullet = 0.3s, others = 0.8s
                        analysis_time = 0.3 if game_speed in ["blitz", "bullet", "ultraBullet"] else 0.8
                        
                        print(f"[*] DEBUG: Analysing for {analysis_time}s (Speed: {game_speed})...")
                        info = engine.analyse(board, chess.engine.Limit(time=analysis_time), multipv=2)

                        if info and "pv" in info[0]:
                            prefix = f"{board.fullmove_number}. " if board.turn == chess.WHITE else f"{board.fullmove_number}... "
                            best = prefix + board.san(info[0]["pv"][0])
                            score = format_eval(info[0].get("score"), user_color)
                            
                            alt_str = "N/A"
                            if len(info) > 1 and info[1].get("pv"):
                                alt_str = prefix + board.san(info[1]["pv"][0]) + " " + format_eval(info[1].get("score"), user_color)

                            print(f"\n[!] YOUR TURN vs {opponent} ({game_id})")
                            print(f"STOCKFISH:    {best:<12} {score}")
                            print(f"ALTERNATIVE:  {alt_str}")
                            print(f"Link: https://lichess.org/{game_id}")
                    else:
                        print(f"[*] DEBUG: Waiting for {opponent} to move...")

    except Exception as exc:
        print(f"[!] DEBUG: Fatal error in game {game_id}: {exc}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--username")
    parser.add_argument("--stockfish-path", default="stockfish")
    args = parser.parse_args()

    token = os.getenv("LICHESS_TOKEN")
    if not token:
        print("[!] Error: Set LICHESS_TOKEN env variable.")
        return

    account = get_account_info(token)
    username = args.username or account.get("username")
    is_bot = account.get("title") == "BOT"

    print(f"--- MONITORING: {username} ---")
    
    # Catch already running games
    for g_id in get_active_game_ids(token):
        print(f"[+] DEBUG: Found active game {g_id}")
        threading.Thread(target=stream_game, args=(g_id, token, username, args.stockfish_path, is_bot), daemon=True).start()

    # Listen for new games
    for event in stream_events(token):
        if event.get("type") == "gameStart":
            g_id = event["game"]["id"]
            print(f"[+] DEBUG: New game starting: {g_id}")
            threading.Thread(target=stream_game, args=(g_id, token, username, args.stockfish_path, is_bot), daemon=True).start()


if __name__ == "__main__":
    main()
