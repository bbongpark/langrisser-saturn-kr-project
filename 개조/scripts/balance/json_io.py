#!/usr/bin/env python3
"""json_io.py — 모든 테이블 모듈이 공유하는 JSON 로드/저장 헬퍼."""
import json


def load_json(path: str) -> list:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(records: list, path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=1)
