try:
    from .doc_tools import word_to_pdf, pdf_to_word
except ImportError:
    pass

try:
    from .student_tools import generate_qr, convert_unit, calculate, programmer_calc
except ImportError:
    pass

try:
    from .pdf_downloader import download_pdf
except ImportError:
    pass

try:
    from .web_search import search_web
except ImportError:
    pass

try:
    from .quiz_generator import generate_quiz
except ImportError:
    pass

try:
    from .translate import translate_text
except ImportError:
    pass

try:
    from .email_tool import send_email_agentic
except ImportError:
    pass

try:
    from .image_tool import generate_image
except ImportError:
    pass

try:
    from .repo_analyzer import analyze_link
except ImportError:
    pass

try:
    from .youtube_transcript import get_youtube_transcript
except ImportError:
    pass

try:
    from .study_system import add_flashcard, get_due_flashcards, review_flashcard, start_pomodoro, get_study_stats
except ImportError:
    pass
