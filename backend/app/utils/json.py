import json
from typing import Any


def dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=True, separators=(",", ":"))


def loads(data: str | None, default: Any) -> Any:
    if not data:
        return default
    return json.loads(data)
