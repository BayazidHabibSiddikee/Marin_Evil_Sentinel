#!/usr/bin/env python3
# tools/translate.py — CLI Dictionary Translator
# Usage: python translate.py --text "I love you" --to bn

import sys, asyncio, argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


LANG_CODES = {
    "english":  "en",
    "chinese":  "zh",
    "spanish":  "es",
    "french":   "fr",
    "japanese": "ja",
    "portuguese":"pt",
    "russian":  "ru",
    "korean":   "ko",
    "german":   "de",
    "italian":  "it",
    "bangla":   "bn",
    "arabic":   "ar",
    "hindi":    "hi",
    "turkish":  "tr",
    "dutch":    "nl",
}

_LANG_NAMES = {v: k.title() for k, v in LANG_CODES.items()}


def translate_text(text: str, dest: str) -> str:
    try:
        from deep_translator import GoogleTranslator
        result = GoogleTranslator(source='en', target=dest).translate(text)
        return result if result else "Translation failed."
    except ImportError:
        try:
            from googletrans import Translator
            result = Translator().translate(text, src='en', dest=dest)
            if asyncio.iscoroutine(result):
                result = asyncio.run(result)
            return result.text
        except Exception:
            return "Translation service unavailable."
    except Exception as e:
        return f"Error: {e}"


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Dictionary translator")
    parser.add_argument('--text', type=str, required=True,
                        help="English text to translate")
    parser.add_argument('--to', type=str, required=True,
                        help="Target language (e.g. bangla, french, bn, fr)")
    args = parser.parse_args()

    lang = args.to.lower().strip()
    dest = LANG_CODES.get(lang, lang)
    lang_name = _LANG_NAMES.get(dest, lang.title())

    print(f"\u2192 Translating to [{lang_name}]")
    translated = translate_text(args.text, dest)
    print(f"English: {args.text}")
    print(f"{lang_name}: {translated}")
