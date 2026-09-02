from __future__ import annotations

import base64
import json
import mimetypes
import os
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ..errors import StageError


class LLMProvider(Protocol):
    def generate_json(self, *, system: str, user: str, image_paths: list[Path] | None = None) -> dict[str, Any]: ...


def _extract_json_text(text: str) -> str:
    value = text.strip()
    if value.startswith("```"):
        lines = value.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        value = "\n".join(lines).strip()
        if value.lower().startswith("json\n"):
            value = value[5:].lstrip()
    return value


def parse_json_response(text: str) -> dict[str, Any]:
    try:
        data = json.loads(_extract_json_text(text))
    except json.JSONDecodeError as exc:
        raise StageError("LLM 返回内容不是有效 JSON。") from exc
    if not isinstance(data, dict):
        raise StageError("LLM JSON 根节点必须为 object。")
    return data


@dataclass
class OpenAICompatibleProvider:
    base_url: str
    model: str
    api_key_env: str
    timeout_seconds: int = 180
    temperature: float = 0.0

    def generate_json(self, *, system: str, user: str, image_paths: list[Path] | None = None) -> dict[str, Any]:
        api_key = os.environ.get(self.api_key_env, "")
        if not api_key:
            raise StageError(
                f"环境变量 {self.api_key_env} 未设置，无法调用 LLM。"
            )

        endpoint = self.base_url.rstrip("/") + "/chat/completions"
        user_content: Any = user
        if image_paths:
            parts: list[dict[str, Any]] = [{"type": "text", "text": user}]
            for path in image_paths:
                path = Path(path)
                if not path.exists() or not path.is_file():
                    raise StageError(f"LLM image 不存在: {path}")
                mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
                encoded = base64.b64encode(path.read_bytes()).decode("ascii")
                parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{encoded}"},
                })
            user_content = parts

        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            "response_format": {"type": "json_object"},
        }
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise StageError(f"LLM HTTP 调用失败: {exc}") from exc

        try:
            content = raw["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise StageError("LLM HTTP 响应缺少 choices[0].message.content。") from exc
        return parse_json_response(str(content))


@dataclass
class CommandProvider:
    command: list[str]
    timeout_seconds: int = 300

    def generate_json(self, *, system: str, user: str, image_paths: list[Path] | None = None) -> dict[str, Any]:
        payload = json.dumps(
            {"system": system, "user": user, "image_paths": [str(x) for x in (image_paths or [])]},
            ensure_ascii=False,
        )
        try:
            proc = subprocess.run(
                self.command,
                input=payload,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=self.timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise StageError(f"LLM command 执行失败: {exc}") from exc
        if proc.returncode != 0:
            raise StageError(
                "LLM command 返回失败："
                + (proc.stderr.strip() or f"exit={proc.returncode}")
            )
        return parse_json_response(proc.stdout)


@dataclass
class FileProvider:
    response_files: list[Path]
    _index: int = 0

    def generate_json(self, *, system: str, user: str, image_paths: list[Path] | None = None) -> dict[str, Any]:
        if self._index >= len(self.response_files):
            raise StageError("FileProvider 没有足够的响应文件。")
        path = self.response_files[self._index]
        self._index += 1
        if not path.exists():
            raise StageError(f"FileProvider 响应文件不存在: {path}")
        return parse_json_response(path.read_text(encoding="utf-8"))


def build_provider(config: dict[str, Any], *, project_root: Path) -> LLMProvider:
    provider = str(config.get("provider", "openai_compatible"))

    if provider == "openai_compatible":
        model = str(config.get("model", "")).strip()
        if not model:
            raise StageError(
                "reconstruction.llm.model 尚未配置。请在 config/default.yaml "
                "或自定义配置文件中指定模型。"
            )
        return OpenAICompatibleProvider(
            base_url=str(config.get("base_url", "https://api.openai.com/v1")),
            model=model,
            api_key_env=str(config.get("api_key_env", "OPENAI_API_KEY")),
            timeout_seconds=int(config.get("timeout_seconds", 180)),
            temperature=float(config.get("temperature", 0.0)),
        )

    if provider == "command":
        command = config.get("command")
        if not isinstance(command, list) or not command:
            raise StageError("reconstruction.llm.command 必须是非空字符串数组。")
        return CommandProvider(
            command=[str(x) for x in command],
            timeout_seconds=int(config.get("timeout_seconds", 300)),
        )

    if provider == "file":
        items = config.get("response_files")
        if not isinstance(items, list) or not items:
            raise StageError("file provider 需要 response_files。")
        paths = []
        for item in items:
            p = Path(str(item))
            if not p.is_absolute():
                p = project_root / p
            paths.append(p.resolve())
        return FileProvider(paths)

    raise StageError(f"未知 reconstruction LLM provider: {provider}")
