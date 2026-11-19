"""Run the review Compose command with just the provider key from a private dotenv."""
import os
from pathlib import Path
import re
import sys


def main():
    if len(sys.argv) < 3:
        raise SystemExit("Usage: with-review-openai.py PRIVATE_ENV COMMAND [ARG ...]")
    text = Path(sys.argv[1]).read_text(encoding="utf-8")
    matches = re.findall(r"^\s*(?:export[ \t]+)?OPENAI_API_KEY[ \t]*=[ \t]*(.*?)\s*$", text, re.MULTILINE)
    if len(matches) != 1:
        raise SystemExit("Expected one OPENAI_API_KEY in the provider file")
    key = matches[0].strip()
    if len(key) >= 2 and key[0] == key[-1] and key[0] in ("'", '"'):
        key = key[1:-1]
    if not re.fullmatch(r"sk-[a-zA-Z0-9_-]+", key):
        raise SystemExit("The provider file does not contain an OpenAI API key")
    os.environ["REVIEW_OPENAI_API_KEY"] = key
    os.execvp(sys.argv[2], sys.argv[2:])


if __name__ == "__main__":
    main()
