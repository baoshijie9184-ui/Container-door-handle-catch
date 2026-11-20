"""Run the review Compose command with its shared OpenAI and OSS settings from a private dotenv."""
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
    # Pass only the shared provider fields. The review database and application settings are independent.
    names = ("ALIYUN_OSS_ENDPOINT", "ALIYUN_OSS_BUCKET", "ALIYUN_OSS_ACCESS_KEY_ID", "ALIYUN_OSS_ACCESS_KEY_SECRET")
    shared = {}
    for name in names:
        values = re.findall(r"^(?:export[ \t]+)?" + name + r"[ \t]*=[ \t]*([^\r\n]*)$", text, re.MULTILINE)
        if len(values) > 1:
            raise SystemExit("Duplicate OSS provider setting: " + name)
        if values:
            value = values[0].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            if not value or any(c.isspace() for c in value):
                raise SystemExit("Invalid OSS provider setting: " + name)
            shared[name] = value
    if shared:
        if set(shared) != set(names):
            raise SystemExit("Incomplete shared OSS connection")
        host = re.fullmatch(r"https://(oss-[a-z0-9-]+\.aliyuncs\.com)/?", shared["ALIYUN_OSS_ENDPOINT"])
        bucket = shared["ALIYUN_OSS_BUCKET"]
        if not host or not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", bucket):
            raise SystemExit("Unexpected shared OSS endpoint or bucket")
        for name, value in shared.items():
            os.environ["REVIEW_" + name] = value
        os.environ["REVIEW_OSS_UPLOAD_HOST"] = bucket + "." + host.group(1)
    os.execvp(sys.argv[2], sys.argv[2:])


if __name__ == "__main__":
    main()
