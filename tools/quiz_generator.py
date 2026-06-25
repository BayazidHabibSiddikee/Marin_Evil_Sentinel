import json
import re

def generate_quiz(topic: str, num_questions: int = 5, rag_context: str = "") -> str:
    """
    Generates a structured multiple-choice quiz using OpenRouter.
    Returns __STRUCTURED__ signal with quiz JSON for frontend rendering.
    """
    prompt = f"""
    You are an expert tutor. Generate a {num_questions}-question multiple-choice quiz on the topic: {topic}.
    
    Use the following reference material if available:
    {rag_context}
    
    Respond ONLY with valid JSON matching this schema exactly:
    {{
      "topic": "topic name",
      "questions": [
        {{
          "question": "What is...?",
          "options": ["A", "B", "C", "D"],
          "answer": "A",
          "explanation": "Because..."
        }}
      ]
    }}
    """
    try:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        import database
        import llm_manager
        llm_info = llm_manager.get_best_llm()
        if not llm_info:
            return "No valid LLM configuration found."
            
        from langchain_core.messages import HumanMessage
        
        max_retries = len(llm_manager.FALLBACK_MODELS)
        for _ in range(max_retries):
            llm, key, model = llm_info
            try:
                response = llm.invoke([HumanMessage(content=prompt)])
                raw = response.content
                break
            except Exception as e:
                if "429" in str(e) or "rate limit" in str(e).lower():
                    llm_manager.report_rate_limit(key, model)
                    llm_info = llm_manager.get_best_llm()
                    if not llm_info:
                        return "All models exhausted. Try again later."
                    continue
                return f"Failed to generate quiz: {e}"
        else:
            return "All models exhausted. Try again later."
        
        # Strip markdown fences
        clean = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
        start = clean.find("{")
        end   = clean.rfind("}") + 1
        
        if start != -1 and end > 0:
            parsed = json.loads(clean[start:end])
            # Return as __STRUCTURED__ for frontend rendering
            return f"__STRUCTURED__{json.dumps(parsed, ensure_ascii=False)}"
            
        return "Failed to parse quiz format from model."
    except Exception as e:
        return f"Failed to generate quiz: {e}"


def render_quiz_html(parsed: dict) -> str:
    """Render quiz JSON as interactive HTML."""
    import json
    topic = parsed.get("topic", "Quiz")
    questions = parsed.get("questions", [])

    # Escape quotes for data attribute
    quiz_json_str = json.dumps(parsed).replace("'", "&#39;")

    html = f'<div class="quiz-container" data-quiz=\'{quiz_json_str}\' style="padding:16px;"><h2 style="color:#ff6b9d;margin-bottom:16px;">Quiz: {topic}</h2>'

    for i, q in enumerate(questions):
        qid = f"q{i}"
        html += f'<div class="quiz-question-block" style="background:#1a1a2e;border-radius:8px;padding:14px;margin-bottom:12px;">'
        html += f'<div style="font-weight:600;margin-bottom:10px;">Q{i+1}: {q["question"]}</div>'
        for j, opt in enumerate(q["options"]):
            letter = chr(65 + j)
            # The value is now the option text, not just the letter
            html += f'<label style="display:flex;align-items:center;gap:8px;padding:6px 10px;margin:3px 0;border-radius:6px;cursor:pointer;background:rgba(255,255,255,.03);" '
            html += f'onmouseover="this.style.background=\'rgba(255,107,157,.1)\'" '
            html += f'onmouseout="this.style.background=\'rgba(255,255,255,.03)\'">'
            html += f'<input type="radio" name="{qid}" value="{opt}" style="accent-color:#ff6b9d;">'
            html += f'<span>{letter}. {opt}</span></label>'
        
        html += f'<div class="quiz-explanation" style="display:none;margin-top:8px;padding:8px;border-radius:6px;font-size:.85rem;"></div>'
        html += '</div>'

    html += f'<button onclick="submitQuiz(this)" style="margin-top:16px;background:#ff6b9d;color:#0f0f23;border:none;padding:10px 20px;border-radius:8px;cursor:pointer;font-weight:bold;width:100%;">Submit Quiz</button>'
    html += '</div>'

    return html


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        print(generate_quiz(" ".join(sys.argv[1:]), 3))
    else:
        print("Usage: python3 quiz_generator.py <topic>")
