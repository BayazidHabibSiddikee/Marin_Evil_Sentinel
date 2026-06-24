from datetime import datetime, timedelta
import json
import sys
from pathlib import Path

# Add project root to path so database can be imported
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import database

# ── Spaced Repetition (Flashcards) ──────────────────────────────────────────

def add_flashcard(topic: str, front: str, back: str) -> str:
    """Adds a new flashcard to the database."""
    with database.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO flashcards (topic, front, back) VALUES (%s, %s, %s) RETURNING id",
            (topic, front, back)
        )
        new_id = cursor.fetchone()[0]
        conn.commit()
    return f"Flashcard {new_id} added to topic '{topic}'."

def get_due_flashcards(topic: str = None) -> list:
    """Gets flashcards that are due for review."""
    with database.get_connection() as conn:
        cursor = conn.cursor()
        query = "SELECT id, topic, front, back FROM flashcards WHERE next_review <= CURRENT_TIMESTAMP"
        params = []
        if topic:
            query += " AND topic = %s"
            params.append(topic)
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
    
    if not rows:
        return []
        
    cards = [{"id": r[0], "topic": r[1], "front": r[2], "back": r[3]} for r in rows]
    return cards

def review_flashcard(card_id: int, quality: int) -> str:
    """
    Quality scale (SuperMemo-2 based):
    0: Complete blackout
    1: Incorrect, but remembered upon seeing answer
    2: Incorrect, but seemed easy to recall
    3: Correct, but required significant effort
    4: Correct, after hesitation
    5: Perfect recall
    """
    if quality < 0 or quality > 5:
        return "Quality must be between 0 and 5."
        
    with database.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT interval_days, ease_factor, reviews FROM flashcards WHERE id = %s", (card_id,))
        row = cursor.fetchone()
        if not row:
            return "Flashcard not found."
            
        interval, ease, reviews = row
        
        if quality >= 3:
            if reviews == 0:
                interval = 1
            elif reviews == 1:
                interval = 6
            else:
                interval = int(interval * ease)
            reviews += 1
        else:
            reviews = 0
            interval = 1
            
        ease = ease + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
        ease = max(1.3, ease)
        
        next_review = datetime.now() + timedelta(days=interval)
        
        cursor.execute(
            "UPDATE flashcards SET next_review = %s, interval_days = %s, ease_factor = %s, reviews = %s WHERE id = %s",
            (next_review, interval, ease, reviews, card_id)
        )
        conn.commit()
    
    return f"Card {card_id} reviewed. Next review in {interval} day(s)."

# ── Pomodoro System ─────────────────────────────────────────────────────────

def start_pomodoro(topic: str, duration_minutes: int = 25) -> str:
    """Starts a Pomodoro session and logs it to study_sessions."""
    with database.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO study_sessions (topic, focus_minutes) VALUES (%s, %s)",
            (topic, duration_minutes)
        )
        conn.commit()
    return f"Logged {duration_minutes} min session for '{topic}'. The frontend timer should be started by the user."

def get_study_stats() -> str:
    """Gets total focus time from study sessions."""
    with database.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT topic, SUM(focus_minutes) FROM study_sessions GROUP BY topic")
        rows = cursor.fetchall()
    
    if not rows:
        return "No study sessions logged yet."
        
    stats = "\n".join([f"- {r[0]}: {r[1]} minutes" for r in rows])
    return f"Study Stats:\n{stats}"
