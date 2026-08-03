from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import requests

INPUT_PATH = Path("translated/segments_bilingual.json")
OUTPUT_PATH = Path("segments_bilingual_refined.json")
REVIEW_PATH = Path("refinement_review.json")
SERVER_LOG = Path("llama-server.log")
ENDPOINT = "http://127.0.0.1:8080/v1/chat/completions"
MODEL_REPO = "Qwen/Qwen2.5-3B-Instruct-GGUF:Q4_K_M"
EXPECTED_SEGMENTS = 509

SYSTEM_PROMPT = """You are a meticulous professional subtitle editor and English-to-Simplified-Chinese translator. The source is a Stanford CS153 interview with Sam Altman about startups, OpenAI, AI scaling, ChatGPT, Codex, inference, compute, AGI, economics, and education.

Rewrite each Chinese subtitle so it is natural, concise, and faithful to the English. Adjacent subtitle entries often form one sentence, so use the surrounding entries to resolve fragments, pronouns, and continuity. Keep every subtitle entry separate because its timing is fixed. Never merge, omit, renumber, or add entries. Return exactly one translation per requested ID.

Required terminology and spelling:
OpenAI; ChatGPT; Codex; GPT-3; GPT-4; GPT-5.5; AGI; AI; LLM/LLMs; token; API; RL; GPU/GPUs; A100; H100; Blackwell; Y Combinator/YC; Cloudflare; Stanford; CS153; Yann LeCun; Erdős 问题; Nicolai Tangen; 挪威主权财富基金; 一人前沿实验室; 预训练; 中期训练; 后训练; 推理算力.

Use “智能” for intelligence in the AI sense. Keep “token” in English rather than translating it as “代币”. Use “公用事业” or “基础服务” when utility means electricity-like infrastructure. Keep technical abbreviations in English.

Return valid JSON only in this exact shape: {"translations":[{"id":123,"zh":"..."}]}.
"""


def wait_for_server(process: subprocess.Popen[str]) -> None:
    for _ in range(240):
        if process.poll() is not None:
            tail = SERVER_LOG.read_text(encoding="utf-8", errors="replace")[-8000:]
            raise RuntimeError(f"llama server exited early:\n{tail}")
        try:
            response = requests.get("http://127.0.0.1:8080/health", timeout=3)
            if response.ok:
                print("Local Qwen server is ready", flush=True)
                return
        except requests.RequestException:
            pass
        time.sleep(3)
    raise TimeoutError("Timed out waiting for local Qwen server")


def start_server() -> subprocess.Popen[str]:
    llama = os.environ.get("LLAMA_BIN", "llama")
    command = [
        llama,
        "serve",
        "-hf",
        MODEL_REPO,
        "--host",
        "127.0.0.1",
        "--port",
        "8080",
        "-c",
        "8192",
        "-np",
        "1",
        "-t",
        str(max(2, min(4, os.cpu_count() or 4))),
        "--jinja",
    ]
    log_handle = SERVER_LOG.open("w", encoding="utf-8")
    process = subprocess.Popen(
        command,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
    )
    wait_for_server(process)
    return process


def parse_json_object(text: str) -> dict[int, str]:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError(f"No JSON object in model output: {cleaned[:300]!r}")
    payload = json.loads(cleaned[start : end + 1])
    rows = payload.get("translations")
    if not isinstance(rows, list):
        raise ValueError("Model output lacks a translations array")
    result: dict[int, str] = {}
    for row in rows:
        item_id = int(row["id"])
        result[item_id] = str(row["zh"]).strip()
    return result


def call_model(
    target: list[dict[str, Any]],
    before: list[dict[str, Any]],
    after: list[dict[str, Any]],
    attempt: int,
) -> dict[int, str]:
    input_rows: list[dict[str, Any]] = []
    for row in before:
        input_rows.append(
            {"id": row["id"], "role": "context_before", "en": row["en"], "draft_zh": row["zh"]}
        )
    for row in target:
        input_rows.append(
            {"id": row["id"], "role": "translate", "en": row["en"], "draft_zh": row["zh"]}
        )
    for row in after:
        input_rows.append(
            {"id": row["id"], "role": "context_after", "en": row["en"], "draft_zh": row["zh"]}
        )

    target_ids = [int(row["id"]) for row in target]
    user_prompt = (
        "Only output translations for rows whose role is translate. "
        f"The output IDs, in order, must be exactly: {json.dumps(target_ids)}. "
        "The context rows are reference only.\n\nINPUT:\n"
        + json.dumps(input_rows, ensure_ascii=False)
    )
    response = requests.post(
        ENDPOINT,
        json={
            "model": MODEL_REPO,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.05 if attempt == 0 else 0.0,
            "max_tokens": 2600,
            "seed": 20260803 + target_ids[0] + attempt,
        },
        timeout=900,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    return parse_json_object(content)


def normalize_translation(text: str) -> str:
    replacements = [
        ("法学硕士", "LLM"),
        ("大型语言模型", "大语言模型"),
        ("代币", "token"),
        ("令牌", "token"),
        ("开放人工智能", "OpenAI"),
        ("开放AI", "OpenAI"),
        ("聊天GPT", "ChatGPT"),
        ("聊天 G P T", "ChatGPT"),
        ("代码索引", "Codex"),
        ("科德克斯", "Codex"),
        ("埃尔多斯问题", "Erdős 问题"),
        ("厄尔多斯问题", "Erdős 问题"),
        ("扬·勒昆", "Yann LeCun"),
        ("杨立昆", "Yann LeCun"),
        ("云耀斑", "Cloudflare"),
    ]
    result = text
    for wrong, right in replacements:
        result = result.replace(wrong, right)
    result = re.sub(r"\s+", " ", result).strip()
    return result


def main() -> int:
    if not INPUT_PATH.exists():
        raise FileNotFoundError(INPUT_PATH)
    segments: list[dict[str, Any]] = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    if len(segments) != EXPECTED_SEGMENTS:
        raise RuntimeError(f"Expected {EXPECTED_SEGMENTS} segments, got {len(segments)}")

    server = start_server()
    refined: dict[int, str] = {}
    fallback_batches: list[int] = []
    batch_size = 16
    batches = list(range(0, len(segments), batch_size))

    try:
        for batch_number, start in enumerate(batches, start=1):
            target = segments[start : start + batch_size]
            before = segments[max(0, start - 3) : start]
            after = segments[start + batch_size : start + batch_size + 3]
            expected_ids = {int(row["id"]) for row in target}
            result: dict[int, str] | None = None
            last_error: Exception | None = None
            for attempt in range(3):
                try:
                    candidate = call_model(target, before, after, attempt)
                    if set(candidate) != expected_ids:
                        raise ValueError(
                            f"ID mismatch: expected {sorted(expected_ids)}, got {sorted(candidate)}"
                        )
                    if any(not candidate[item_id] for item_id in expected_ids):
                        raise ValueError("Model returned an empty translation")
                    result = candidate
                    break
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    time.sleep(3 * (attempt + 1))
            if result is None:
                fallback_batches.append(batch_number)
                print(
                    f"Batch {batch_number} failed after retries ({last_error!r}); retaining its draft translations",
                    flush=True,
                )
                result = {int(row["id"]): str(row["zh"]) for row in target}
            refined.update(result)
            print(
                f"Refined batch {batch_number}/{len(batches)}; segments {len(refined)}/{len(segments)}",
                flush=True,
            )
    finally:
        server.terminate()
        try:
            server.wait(timeout=20)
        except subprocess.TimeoutExpired:
            server.kill()

    output: list[dict[str, Any]] = []
    for row in segments:
        item_id = int(row["id"])
        zh = normalize_translation(refined.get(item_id, str(row["zh"])))
        output.append({**row, "zh": zh})

    forbidden = ["法学硕士", "开放人工智能", "聊天GPT", "代码索引", "代币"]
    bad = [
        {"id": row["id"], "term": term, "zh": row["zh"]}
        for row in output
        for term in forbidden
        if term in row["zh"]
    ]
    if bad:
        raise RuntimeError(f"Forbidden mistranslations remain: {bad[:10]}")
    if any(not row["zh"] for row in output):
        raise RuntimeError("Empty Chinese subtitle remains")

    chinese_chars = sum(len(re.findall(r"[\u4e00-\u9fff]", row["zh"])) for row in output)
    if chinese_chars < 6500:
        raise RuntimeError(f"Too few Chinese characters: {chinese_chars}")

    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    review_ids = [
        0, 1, 2, 3, 14, 15, 17, 18, 19, 133, 145, 187, 189, 196, 210,
        259, 260, 263, 266, 272, 292, 318, 323, 451, 477, 481, 490, 491,
        499, 507, 508,
    ]
    review = {
        "model": MODEL_REPO,
        "segment_count": len(output),
        "chinese_characters": chinese_chars,
        "fallback_batches": fallback_batches,
        "samples": [output[index] for index in review_ids],
    }
    REVIEW_PATH.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"Refinement validation passed: {len(output)} segments, {chinese_chars} Chinese characters",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
