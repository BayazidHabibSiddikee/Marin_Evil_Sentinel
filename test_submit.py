from tools.quiz_generator import render_quiz_html
import json

quiz = {
    "topic": "Python",
    "questions": [
        {
            "question": "What is Python?",
            "options": ["Snake", "Language", "Car", "don't"],
            "answer": "Language",
            "explanation": "Because."
        }
    ]
}

html = render_quiz_html(quiz)
with open('test_submit.html', 'w') as f:
    f.write(f"""
    <html><body>
    {html}
    <div id="msg-input"></div>
    <script>
        const input = document.getElementById('msg-input');
        async function saveToolContext() {{ return; }}
        async function sendMessage() {{ console.log("Sent!"); }}
        async function submitQuiz(btn) {{
            const container = btn.closest('.quiz-container');
            const quizData = JSON.parse(container.dataset.quiz.replace(/&#39;/g, "'"));
            console.log(quizData);
            btn.textContent = "Done";
        }}
    </script>
    </body></html>
    """)
