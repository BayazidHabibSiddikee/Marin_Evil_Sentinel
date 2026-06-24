import os
import json
import asyncio
import re
from typing import TypedDict, Annotated, Sequence, Optional, List

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, END

# ── Local Tools ─────────────────────────────────────────────────────────────

@tool
def search_web(query: str) -> str:
    """Search the web using DuckDuckGo."""
    from tools.web_search import search_web as _search
    return _search(query)

@tool
def download_pdf(url: str) -> str:
    """Download a PDF and automatically index it into the RAG system."""
    from tools.pdf_downloader import download_pdf as _down
    return _down(url)

@tool
def calculate(expression: str) -> str:
    """Calculate a math expression."""
    from tools.student_tools import calculate as _calc
    return _calc(expression)

@tool
def generate_quiz(topic: str) -> str:
    """Generate a multiple-choice quiz on a topic."""
    from tools.quiz_generator import generate_quiz as _quiz
    return _quiz(topic)

@tool
def start_timer(task_name: str) -> str:
    """Start a study timer for a specific task."""
    import database
    tid = database.start_timer(task_name)
    return f"Timer started for '{task_name}' with ID {tid}."

@tool
def end_timer(timer_id: int) -> str:
    """End a running study timer by ID."""
    import database
    database.end_timer(timer_id)
    return f"Timer {timer_id} ended."

@tool
def word_to_pdf(path: str) -> str:
    """Convert a word document to PDF."""
    from tools.doc_tools import word_to_pdf as _wtp
    return _wtp(path)

@tool
def pdf_to_word(path: str) -> str:
    """Convert a PDF document to Word."""
    from tools.doc_tools import pdf_to_word as _ptw
    return _ptw(path)

@tool
def translate(text: str, to: str) -> str:
    """Translate text to another language."""
    from tools.translate import translate_text as _tr
    return _tr(text, to)

@tool
def youtube_transcript(url: str) -> str:
    """Get the transcript of a YouTube video."""
    from tools.youtube_transcript import get_youtube_transcript as _yt
    return _yt(url)

@tool
def analyze_link(url: str) -> str:
    """Analyze a generic link or git repository URL."""
    from tools.repo_analyzer import analyze_link as _al
    return _al(url)

@tool
def send_email(recipient_email: str, subject: str, body: str) -> str:
    """Send an email using saved credentials."""
    from tools.email_tool import send_email_agentic
    return send_email_agentic(recipient_email, subject, body)

@tool
def add_flashcard(topic: str, front: str, back: str) -> str:
    """Add a flashcard to the spaced repetition system."""
    from tools.study_system import add_flashcard as _af
    return _af(topic, front, back)

@tool
def get_due_flashcards(topic: str = None) -> str:
    """Get flashcards due for review. Optionally filter by topic."""
    from tools.study_system import get_due_flashcards as _gdf
    return _gdf(topic)

@tool
def review_flashcard(card_id: int, quality: int) -> str:
    """Review a flashcard. Quality is 0-5 (0=blackout, 5=perfect)."""
    from tools.study_system import review_flashcard as _rf
    return _rf(card_id, quality)

@tool
def start_pomodoro(topic: str, duration_minutes: int = 25) -> str:
    """Start a pomodoro focus session."""
    from tools.study_system import start_pomodoro as _sp
    return _sp(topic, duration_minutes)

@tool
def get_study_stats() -> str:
    """Get statistics of completed study sessions."""
    from tools.study_system import get_study_stats as _gss
    return _gss()

ALL_TOOLS = [search_web, download_pdf, calculate, generate_quiz, start_timer, end_timer, word_to_pdf, pdf_to_word, translate, youtube_transcript, analyze_link, send_email, add_flashcard, get_due_flashcards, review_flashcard, start_pomodoro, get_study_stats]
tools_by_name = {t.name: t for t in ALL_TOOLS}

# ── Agent State ──────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], lambda x, y: x + y]
    plan: List[dict]
    tool_outputs: dict
    user_vibe: str

# ── Nodes ────────────────────────────────────────────────────────────────────

STRATEGIST_SYSTEM = """You are Marin's Strategist. Build a JSON plan to use tools if needed.
TOOLS: {tools}
Output ONLY a JSON array: [{{"action": "tool_name", "args": {{...}}, "rationale": "..."}}]
If no tool needed: [{{"action": "respond", "args": {{}}, "rationale": "..."}}]
"""

async def node_strategist(state: AgentState) -> dict:
    last = state["messages"][-1]
    user_msg = last.content if hasattr(last, 'content') else last.get("content", str(last))
    
    plan = []
    try:
        import llm_manager
        llm_info = llm_manager.get_best_llm()
        if not llm_info:
            raise ValueError("No valid LLM configuration found.")
        llm = llm_info[0]
        
        sys_msg = SystemMessage(content=STRATEGIST_SYSTEM.format(tools=[t.name for t in ALL_TOOLS]))
        
        # Keep recent context for strategist
        recent_msgs = list(state["messages"])[-5:]
        resp = await llm.ainvoke([sys_msg] + recent_msgs)
        
        match = re.search(r'\[\s*\{.*\}\s*\]', resp.content, re.DOTALL)
        plan = json.loads(match.group(0)) if match else [{"action": "respond", "args": {}, "rationale": resp.content}]
    except Exception as e:
        print(f"Strategist error: {e}")
        plan = [{"action": "respond", "args": {}, "rationale": "Proceeding without tools due to error."}]
    
    return {"plan": plan}

async def node_executor(state: AgentState) -> dict:
    plan = state.get("plan", [])
    tool_outputs = state.get("tool_outputs", {})
    completed = len([k for k in tool_outputs if k.startswith("step_")])
    
    if completed >= len(plan):
        return {"tool_outputs": tool_outputs}

    step = plan[completed]
    action = step.get("action", "respond")
    args = step.get("args", {})
    
    if action == "respond":
        tool_outputs["__final_response__"] = step.get("rationale", "I'm ready.")
        return {"tool_outputs": tool_outputs}

    print(f"[Executor] Running {action} with {args}...")
    if action in tools_by_name:
        try:
            res = await tools_by_name[action].ainvoke(args)
            tool_outputs[f"step_{completed}_{action}"] = str(res)
        except Exception as e:
            tool_outputs[f"step_{completed}_{action}"] = f"Error: {e}"
    else:
        tool_outputs[f"step_{completed}_{action}"] = "Tool not found."
    
    return {"tool_outputs": tool_outputs}

async def persona_node(state: AgentState) -> dict:
    tool_outputs = state.get("tool_outputs", {})
    raw_results = [v for k, v in sorted(tool_outputs.items()) if k.startswith("step_")]
    final_raw = tool_outputs.get("__final_response__", "")
    
    context = "\n\n".join(raw_results) if raw_results else final_raw
    if not context: context = "Task completed."

    return {"tool_outputs": {"__context_for_marin__": context}}

# ── Graph Logic ──────────────────────────────────────────────────────────────

def route_after_executor(state: AgentState):
    if "__final_response__" in state.get("tool_outputs", {}) or len([k for k in state.get("tool_outputs", {}) if k.startswith("step_")]) >= len(state.get("plan", [])):
        return "persona"
    return "executor"

workflow = StateGraph(AgentState)
workflow.add_node("strategist", node_strategist)
workflow.add_node("executor", node_executor)
workflow.add_node("persona", persona_node)

workflow.set_entry_point("strategist")
workflow.add_conditional_edges("strategist", lambda x: "persona" if x.get("plan") and x["plan"][0]["action"] == "respond" else "executor")
workflow.add_conditional_edges("executor", route_after_executor)
workflow.add_edge("persona", END)

agent = workflow.compile()

async def run_langgraph_pipeline(messages: list) -> str:
    """Runs the 3-node pipeline and returns the context string to feed to Marin's streaming persona."""
    state = await agent.ainvoke({"messages": messages, "plan": [], "tool_outputs": {}})
    return state["tool_outputs"].get("__context_for_marin__", "")
