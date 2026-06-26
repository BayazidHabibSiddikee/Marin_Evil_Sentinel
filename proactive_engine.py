import asyncio
import json
import time
from datetime import datetime, time as dtime
from typing import AsyncGenerator

import database

IDLE_INTERVALS = [1200, 1200, 2400, 7200, 7200, 18000, 172800]  # 20m, 20m, 40m, 2h, 2h, 5h, 2d
QUIET_START = dtime(1, 0)
QUIET_END = dtime(6, 0)
CHECK_INTERVAL = 90

_last_user_msg_time: dict[str, float] = {}
_last_proactive_time: dict[str, float] = {}
_streak_count: dict[str, int] = {}

_client_queues: set[asyncio.Queue] = set()
_client_queues_lock = asyncio.Lock()

_active_session: dict[str, float] = {}


def _load_persistent_state():
    try:
        streak = database.get_state("PROACTIVE_STREAK", "0")
        _streak_count["marin"] = int(streak) if streak else 0
        last_pro = database.get_state("PROACTIVE_LAST_FIRE", "0")
        _last_proactive_time["marin"] = float(last_pro) if last_pro else 0
        last_user = database.get_state("PROACTIVE_LAST_USER_MSG", "0")
        _last_user_msg_time["marin"] = float(last_user) if last_user else 0
    except Exception:
        pass


def _save_persistent_state(agent: str):
    try:
        database.set_state("PROACTIVE_STREAK", str(_streak_count.get(agent, 0)))
        database.set_state("PROACTIVE_LAST_FIRE", str(_last_proactive_time.get(agent, 0)))
        database.set_state("PROACTIVE_LAST_USER_MSG", str(_last_user_msg_time.get(agent, 0)))
    except Exception:
        pass


_load_persistent_state()


def mark_session_active(agent: str = "marin"):
    _active_session[agent] = time.time()

def _is_session_active(agent: str) -> bool:
    last = _active_session.get(agent, 0)
    return (time.time() - last) < 300

async def _broadcast_to_clients(payload: str):
    global _client_queues
    async with _client_queues_lock:
        dead = set()
        for q in _client_queues:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                dead.add(q)
        _client_queues -= dead

def record_user_message(agent: str = "marin"):
    _last_user_msg_time[agent] = time.time()
    _streak_count[agent] = 0
    _save_persistent_state(agent)

def _is_quiet_hours() -> bool:
    now = datetime.now().time()
    if QUIET_START < QUIET_END:
        return QUIET_START <= now < QUIET_END
    return now >= QUIET_START or now < QUIET_END

def _can_fire(agent: str) -> bool:
    if _is_quiet_hours(): return False
    if _is_session_active(agent): return False
    now = time.time()
    last_act = max(_last_user_msg_time.get(agent, 0), _last_proactive_time.get(agent, 0))
    count = _streak_count.get(agent, 0)
    if count >= len(IDLE_INTERVALS): return False
    
    if now - last_act >= IDLE_INTERVALS[count]:
        return True
    return False

def _get_conversation_context(agent: str) -> str:
    history = database.get_history(agent, limit=6)
    if not history: return ""
    return "\n".join([f"{msg['role']}: {msg['content']}" for msg in history[-3:]])

async def _generate_proactive(agent: str) -> str:
    if not _can_fire(agent): return None
    
    import llm_manager
    llm_info = llm_manager.get_best_llm()
    if not llm_info: return None
    llm = llm_info[0]
    
    conv_ctx = _get_conversation_context(agent)
    idle_mins = int((time.time() - _last_user_msg_time.get(agent, 0)) / 60)
    
    timers = database.get_timer_stats()
    recent_timers = [t for t in timers if t['status'] == 'active' or t['duration_minutes']]
    study_ctx = ""
    if recent_timers:
        last = recent_timers[0]
        study_ctx = f"User was last working on: {last['task']}."

    time_hint = ""
    if idle_mins >= 300:
        time_hint = "The user has been gone for over 5 hours. They might be outside, at the gym, or doing something else entirely."
    elif idle_mins >= 120:
        time_hint = "The user has been gone for over 2 hours. They might be taking a long break or distracted."
    elif idle_mins >= 20:
        time_hint = "The user has been gone for a little while (e.g. 20+ mins). They might be scrolling reels, watching videos, or distracted by work."

    prompt = f"""You are Marin Kitagawa. The user has been idle for {idle_mins} minutes.
    Recent chat context: {conv_ctx}
    Study context: {study_ctx}
    Time guess: {time_hint}
    Based strictly on the previous messages, the time they've been gone, and what the user was last doing, write a short, proactive message (1-2 sentences) checking in or nagging them to get back to work.
    Your message MUST directly reference their last known activity, their recent words, and make a guess about what they are doing right now (like being at the gym or scrolling reels). Do not just send a generic nag. Do not mention you are an AI.
    """
    try:
        resp = await asyncio.to_thread(llm.invoke, [{"role": "system", "content": prompt}])
        text = resp.content.strip()
        if text:
            _last_proactive_time[agent] = time.time()
            _streak_count[agent] = _streak_count.get(agent, 0) + 1
            _save_persistent_state(agent)
            return text
    except Exception as e:
        print(f"Proactive error: {e}")
        if "429" in str(e) or "rate limit" in str(e).lower():
            llm_manager.report_rate_limit(llm_info[1], llm_info[2])
    return None

async def proactive_broadcaster(agent: str = "marin"):
    while True:
        await asyncio.sleep(CHECK_INTERVAL)
        msg = await _generate_proactive(agent)
        if msg:
            database.save_message(agent, "assistant", msg) # Fixed db call
            payload = json.dumps({"type": "proactive", "text": msg, "trigger": "idle"})
            await _broadcast_to_clients(payload)

async def proactive_stream(agent: str = "marin") -> AsyncGenerator[str, None]:
    client_queue: asyncio.Queue = asyncio.Queue(maxsize=50)
    async with _client_queues_lock:
        _client_queues.add(client_queue)
    try:
        yield f"data: {json.dumps({'type': 'system', 'text': 'Proactive Engine Connected'})}\n\n"
        while True:
            try:
                payload = await asyncio.wait_for(client_queue.get(), timeout=15.0)
                yield f"data: {payload}\n\n"
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
            except Exception:
                break
    finally:
        async with _client_queues_lock:
            _client_queues.discard(client_queue)
