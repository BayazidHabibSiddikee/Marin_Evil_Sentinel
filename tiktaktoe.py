#!/usr/bin/env python3
# games/tiktaktoe.py — LLM (System/O) vs User (X) with async support
import asyncio
import random
import re
import sys
import threading
from pathlib import Path
from turtle import *
from tkinter import messagebox
import ollama
import subprocess

subprocess.Popen(["ollama","serve"],stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


USER_NAME = "Himel"


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ── Regex Helper: Extract moves from LLM responses ──────────────────────────
def extract_move(text: str, available: list[str]) -> str | None:
    """
    Extract Tic Tac Toe move (1-9) from LLM response.
    Supports patterns: **5**, [5], (5), or just bare digit.
    Returns validated cell string or None.
    """
    # Priority 1: **digit** pattern (Marin's style)
    match = re.search(r'\*\*(\d)\*\*', text)
    if match:
        cell = match.group(1)
        if cell in available:
            return cell
    
    # Priority 2: [digit] or (digit)
    
    match = re.search(r'[\[\(](\d)[\]\)]', text)
    if match:
        cell = match.group(1)
        if cell in available:
            return cell
    
    # Priority 3: Bare digit near move keywords
    '''
    move_context = re.search(r'(pick|take|play|choose|move|cell)\s*[#:.]?\s*(\d)', text, re.I)
    if move_context:
        cell = move_context.group(2)
        if cell in available:
            return cell
    '''
    if "I will pick cell" in text:
        move_context=re.search(r'\d+',text)
        if move_context:
            cell = move_context.group(1)
            if cell in available:
                return cell
    
    # Fallback: Any digit 1-9 in text
    digits = re.findall(r'[1-9]', text)
    for d in digits:
        if d in available:
            return d
    
    return None


class TikTakToe:
    """LLM-powered Tic Tac Toe: System (O) vs User (X)."""

    def __init__(self, model: str = "marin"):
        self.cell_center = {
            '1': (-200, 200), '2': (0, 200),   '3': (200, 200),
            '4': (-200, 0),   '5': (0, 0),     '6': (200, 0),
            '7': (-200, -200),'8': (0, -200),  '9': (200, -200),
        }
        self.board = {k: None for k in self.cell_center}
        self.user_mark = 'X'
        self.system_mark = 'O'
        self.turn = 'system'
        self.round = 0
        self.available = list(self.cell_center.keys())
        self.model_name = model  # "marin" for personality, or any ollama model

    # ── LLM Notification Hook ───────────────────────────────────────────────
    def llm_notify(self, event: str, detail: str) -> str:
        """Format board state for LLM consumption + logging."""
        rows = []
        for r in range(3):
            line = []
            for c in range(3):
                cell = str(r * 3 + c + 1)
                mark = self.board[cell]
                line.append(mark if mark else cell)
            rows.append(' | '.join(line))
        
        text = (
            f"--- {event} ---\n"
            f"Detail: {detail}\n"
            f"Board:\n"
            f"{rows[0]}\n---------\n{rows[1]}\n---------\n{rows[2]}\n"
            f"Available: {self.available}\n"
            f"Turn: {self.turn}\n"
        )
        print(text, flush=True)
        return text

    # ── Drawing ─────────────────────────────────────────────────────────────
    def draw_board(self):
        Screen()
        setup(600, 600, 10, 70)
        tracer(False)
        title("Tic Tac Toe — AI (O) vs You (X)")
        bgcolor('light pink')
        hideturtle()
        pensize(5)
        for i in (-100, 100):
            up(); goto(300, i); down(); goto(-300, i); up()
            up(); goto(i, -300); down(); goto(i, 300); up()
        for cell, center in self.cell_center.items():
            goto(center)
            write(cell, align='center', font=('Arial', 30, 'italic'))
        update()
        self.llm_notify("GAME_START", "AI=O, User=X, AI moves first")

    def draw_mark(self, cell: str, mark: str):
        x, y = self.cell_center[cell]
        goto(x, y - 40)
        color('blue' if mark == 'X' else 'red')
        write(mark, align='center', font=('Arial', 80, 'bold'))
        color('black')
        update()

    # ── Game Logic ──────────────────────────────────────────────────────────
    def _winner(self, mark: str) -> bool:
        combos = [
            ['1','2','3'],['4','5','6'],['7','8','9'],
            ['1','4','7'],['2','5','8'],['3','6','9'],
            ['1','5','9'],['3','5','7'],
        ]
        return any(all(self.board[c] == mark for c in combo) for combo in combos)

    def _finish(self, msg: str):
        self.turn = None
        self.available = []
        messagebox.showinfo("Game Over", msg)
        self.llm_notify("GAME_OVER", msg)

    def make_move(self, cell: str, mark: str):
        self.round += 1
        self.available.remove(cell)
        self.board[cell] = mark
        self.draw_mark(cell, mark)
        
        if self._winner(mark):
            winner = "Marin" if mark == self.system_mark else "You"
            self._finish(f"{winner} win{'s' if winner == 'Marin' else ''}! 🎉")
        elif self.round == 9:
            self._finish("It's a tie! 🤝")
        else:
            self.turn = "user" if mark == self.system_mark else "system"

    # ── Async LLM Move Generator ────────────────────────────────────────────
    async def _get_llm_move_async(self) -> str | None:
        """Async wrapper for LLM move suggestion."""
        board_state = self.llm_notify("REQUESTING_AI_MOVE", "Thinking...")
        available_str = ", ".join(self.available)
        
        prompt = (
            #f"You are playing Tic Tac Toe as 'O'. {USER_NAME} is 'X'.\n"
            f"Current board:\n{board_state}\n"
            f"Available cells: {available_str}\n"
            #f"Rules: First to get 3 in a row wins. If no one wins after 9 moves, it's a tie.\n"
            #f"Your goal: Win the game while having fun. Think strategically and enjoy the game!\n"
            #f"Please make your move in the format: \"I'll pick **[cell]**!\""
            #f"Where [cell] is a number between 1 and 9.\n"
            #f"You got the first move, make your move\n"
        )
        
        try:
            # Run blocking ollama call in thread pool
            
            loop = asyncio.get_running_loop()
            res = await loop.run_in_executor(
                None, 
                lambda: ollama.chat(
                    model=self.model_name, 
                    messages=[{"role": "user", "content": prompt}]
                )
            )
            content = res["message"]["content"].strip()
            print(f"[LLM Response] {content}...")
            return extract_move(content, self.available)
        except Exception as e:
            print(f"[LLM Error] {type(e).__name__}: {e}")
            return None

    # ── System (AI) Move Handler ────────────────────────────────────────────
    def system_move(self):
        """AI's turn: async LLM call + UI update on main thread."""
        if not self.available or self.turn != "system":
            return
        
        async def _async_ai_turn():
            cell = await self._get_llm_move_async()
            
            # Fallback to random if LLM fails
            '''
            if not cell and self.available:
                cell = random.choice(self.available)
                print(f"[Fallback] Random move: {cell}")
            '''
            # Schedule UI update on main Tkinter thread
            if cell:
                # Use ontimer to jump back to main thread
                ontimer(lambda: self._apply_move_safe(cell), 10)
        
        # Start async task in new event loop (turtle mainloop is blocking)
        def _run_async():
            try:
                asyncio.run(_async_ai_turn())
            except RuntimeError:
                # Event loop already running? Use new thread with fresh loop
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(_async_ai_turn())
                loop.close()
        
        threading.Thread(target=_run_async, daemon=True).start()

    def _apply_move_safe(self, cell: str):
        """Thread-safe move application (must run on main turtle thread)."""
        if cell in self.available:
            self.make_move(cell, self.system_mark)
            self.llm_notify("SYSTEM_MOVE", f"AI placed O at cell {cell}")
            # After AI moves, check if game continues
            if self.available and self.turn == "user":
                # Ready for user input (onscreenclick handles this)
                pass

    # ── User Move Handler ───────────────────────────────────────────────────
    def user_move(self, x: float, y: float):
        """Handle user click on board."""
        if self.turn != "user":
            return
        if not (-300 < x < 300 and -300 < y < 300):
            return
        
        # Convert click coordinates to cell number
        col = int((x + 300) // 200) + 1
        row = int((y + 300) // 200) + 1
        cell = str((3 - row) * 3 + col)
        
        if cell not in self.available:
            messagebox.showerror("Invalid Move", "Cell already occupied! 😊")
            return
        
        self.make_move(cell, self.user_mark)
        self.llm_notify("USER_MOVE", f"You placed X at cell {cell}")
        
        # Trigger AI move after brief delay if game continues
        if self.available and self.turn == "system":
            ontimer(self.system_move, 600)  # 600ms pause for realism

    # ── Main Loop ───────────────────────────────────────────────────────────
    def main(self):
        while True:
            self.draw_board()
            # Start with AI move after brief delay
            ontimer(self.system_move, 800)
            # Register user click handler
            onscreenclick(self.user_move)
            # Start turtle event loop (blocking)
            done()


def launch_game(model: str = "marin"):
    """Entry point for Marin or direct launch."""
    print(f"[System] Launching Tic Tac Toe with LLM: {model} 🎮")
    game = TikTakToe(model=model)
    game.main()


if __name__ == '__main__':
    launch_game()