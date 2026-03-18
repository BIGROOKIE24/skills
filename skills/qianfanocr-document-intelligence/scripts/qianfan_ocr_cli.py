#!/usr/bin/env python3

import argparse
import base64
import concurrent.futures
import json
import mimetypes
import os
import re
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
DEFAULT_ENV_PATH = SKILL_ROOT / ".env"
DEFAULT_URL = "https://qianfan.baidubce.com/v2/chat/completions"
DEFAULT_MODEL = "qianfan-ocr"
DEFAULT_TIMEOUT_SECONDS = 60
CLI_NAME = "Qianfan OCR Cli"
ENV_MODEL = "QIANFAN_MODEL"
ENV_TOKEN = "QIANFAN_TOKEN"
ENV_URL = "QIANFAN_URL"

_THINK_RE = re.compile(r"^\s*<think>(.*?)</think>\s*", re.DOTALL)


class CliError(Exception):
    pass


class HttpResponse(object):
    def __init__(self, raw_response: Any) -> None:
        self._raw_response = raw_response
        self._body = None  # type: Optional[bytes]
        self.status_code = raw_response.getcode()
        self.reason = getattr(raw_response, "reason", "") or ""
        self.headers = raw_response.headers

    def _get_charset(self) -> str:
        charset = self.headers.get_content_charset()
        return charset or "utf-8"

    def read(self) -> bytes:
        if self._body is None:
            try:
                self._body = self._raw_response.read()
            except OSError as exc:
                raise CliError(f"failed to read response body: {exc}") from exc
        return self._body

    @property
    def text(self) -> str:
        return self.read().decode(self._get_charset(), errors="replace")

    def json(self) -> Any:
        return json.loads(self.text)

    def close(self) -> None:
        self._raw_response.close()


class CliArgs(object):
    def __init__(
        self,
        prompt: str,
        model: str,
        token: str,
        url: str,
        timeout: float,
        max_tokens: int,
        thinking: bool,
        skip_special_tokens: bool,
        min_dynamic_patch: Optional[int],
        max_dynamic_patch: Optional[int],
        batch: bool,
        concurrency: int,
        log_file: Optional[str],
        images: Sequence[str],
    ) -> None:
        self.prompt = prompt
        self.model = model
        self.token = token
        self.url = url
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.thinking = thinking
        self.skip_special_tokens = skip_special_tokens
        self.min_dynamic_patch = min_dynamic_patch
        self.max_dynamic_patch = max_dynamic_patch
        self.batch = batch
        self.concurrency = concurrency
        self.log_file = log_file
        self.images = tuple(images)


def append_log(log_file: Optional[str], payload: Dict[str, Any]) -> None:
    if not log_file:
        return
    path = Path(log_file).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"ts": datetime.now(timezone.utc).isoformat(), **payload}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=True) + "\n")


def strip_thinking(text: str) -> str:
    m = _THINK_RE.match(text)
    if not m:
        return text
    return text[m.end():].strip()


def extract_text_content(value: Any) -> Optional[str]:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if isinstance(text, str):
                parts.append(text)
        return "".join(parts)
    return None


def first_choice(payload: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return None
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    choice = choices[0]
    return choice if isinstance(choice, dict) else None


def extract_choice_content(choice: Dict[str, Any]) -> Optional[str]:
    message = choice.get("message")
    if isinstance(message, dict):
        content = extract_text_content(message.get("content"))
        if content is not None:
            return content

    text = extract_text_content(choice.get("text"))
    if text is not None:
        return text
    return None


def parse_response_content(payload: Dict[str, Any]) -> str:
    choice = first_choice(payload)
    if choice is None:
        raise CliError("response missing valid choices[0]")
    content = extract_choice_content(choice)
    if content is None:
        raise CliError("no readable text field found in response")
    return content


def is_remote_image_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def local_image_to_data_url(image_path: str) -> str:
    path = Path(image_path)
    if not path.is_file():
        raise CliError(f"image file not found: {image_path}")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise CliError(f"failed to read image file: {image_path}: {exc}") from exc
    mime_type, _ = mimetypes.guess_type(path.name)
    mime = mime_type or "application/octet-stream"
    encoded = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def image_source_to_url(image_source: str) -> str:
    if is_remote_image_url(image_source):
        return image_source
    return local_image_to_data_url(image_source)


def build_user_content(args: CliArgs) -> List[Dict[str, Any]]:
    prompt = args.prompt
    if args.thinking:
        prompt += "<think>"

    content = [{"type": "text", "text": prompt}]
    for image_source in args.images:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": image_source_to_url(image_source)},
            }
        )
    return content


def build_body(args: CliArgs) -> Dict[str, Any]:
    body = {
        "model": args.model,
        "max_tokens": args.max_tokens,
        "stream": False,
        "skip_special_tokens": args.skip_special_tokens,
    }
    if args.thinking:
        body["chat_template_kwargs"] = {"enable_thinking": True}
    mm_processor_kwargs = {}
    if args.min_dynamic_patch is not None:
        mm_processor_kwargs["min_dynamic_patch"] = args.min_dynamic_patch
    if args.max_dynamic_patch is not None:
        mm_processor_kwargs["max_dynamic_patch"] = args.max_dynamic_patch
    if mm_processor_kwargs:
        body["mm_processor_kwargs"] = mm_processor_kwargs
    body["messages"] = [{"role": "user", "content": build_user_content(args)}]
    return body


def env_or_default(name: str, fallback: str) -> str:
    value = os.environ.get(name)
    if value:
        return value
    return fallback


def load_dotenv(path: Path) -> Dict[str, str]:
    if not path.is_file():
        return {}
    values: Dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise CliError(f"failed to read env file: {path}: {exc}") from exc
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def resolve_token(cli_token: Optional[str]) -> str:
    if cli_token:
        return cli_token
    env_token = os.environ.get(ENV_TOKEN)
    if env_token:
        return env_token
    dotenv_token = load_dotenv(DEFAULT_ENV_PATH).get(ENV_TOKEN)
    if dotenv_token:
        return dotenv_token
    raise CliError(
        f"{ENV_TOKEN} 环境变量未设置。请提供百度千帆 API Key，或写入 "
        f"{DEFAULT_ENV_PATH}。如果您暂时没有 API Key，请到 "
        "https://cloud.baidu.com/product-s/qianfan_home 注册获取。"
    )


def positive_timeout_seconds(value: str) -> float:
    try:
        timeout = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid timeout value: {value}") from exc
    if timeout <= 0:
        raise argparse.ArgumentTypeError("timeout must be greater than 0")
    return timeout


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid integer value: {value}") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than 0")
    return parsed


def parse_args(argv: Optional[Sequence[str]] = None) -> CliArgs:
    parser = argparse.ArgumentParser(description=CLI_NAME)
    parser.add_argument("prompt", help="User prompt")
    parser.add_argument(
        "--model",
        default=env_or_default(ENV_MODEL, DEFAULT_MODEL),
        help=f"Model name (env: {ENV_MODEL})",
    )
    parser.add_argument(
        "--token",
        help=f"Bearer token (env/.env: {ENV_TOKEN})",
    )
    parser.add_argument(
        "--url",
        default=env_or_default(ENV_URL, DEFAULT_URL),
        help=f"API endpoint (env: {ENV_URL})",
    )
    parser.add_argument(
        "--timeout",
        type=positive_timeout_seconds,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"Request timeout in seconds (default: {DEFAULT_TIMEOUT_SECONDS})",
    )
    parser.add_argument("--max-tokens", type=int, default=4096, help="Maximum output tokens")
    parser.add_argument(
        "--skip-special-tokens",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Whether to skip special tokens. Default: false.",
    )
    parser.add_argument(
        "--thinking",
        action="store_true",
        help="Enable thinking mode for complex document parsing with ambiguous labels or unclear reading order",
    )
    parser.add_argument(
        "--min-dynamic-patch",
        type=positive_int,
        help="Optional mm_processor_kwargs.min_dynamic_patch override for complex layouts",
    )
    parser.add_argument(
        "--max-dynamic-patch",
        type=positive_int,
        help="Optional mm_processor_kwargs.max_dynamic_patch override for complex layouts",
    )
    parser.add_argument(
        "--log-file",
        help="Optional JSONL log file for invocation records",
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Process each --image independently and emit one result per image",
    )
    parser.add_argument(
        "--concurrency",
        type=positive_int,
        default=1,
        help="Concurrency for --batch mode. Default: 1",
    )
    parser.add_argument(
        "--image",
        action="append",
        required=True,
        default=[],
        metavar="PATH_OR_URL",
        help="Required image input (local path or URL). Repeat for multiple images.",
    )
    ns = parser.parse_args(argv)
    if (
        ns.min_dynamic_patch is not None
        and ns.max_dynamic_patch is not None
        and ns.min_dynamic_patch > ns.max_dynamic_patch
    ):
        parser.error("--min-dynamic-patch cannot be greater than --max-dynamic-patch")

    return CliArgs(
        prompt=ns.prompt,
        model=ns.model,
        token=resolve_token(ns.token),
        url=ns.url,
        timeout=ns.timeout,
        max_tokens=ns.max_tokens,
        thinking=ns.thinking,
        skip_special_tokens=ns.skip_special_tokens,
        min_dynamic_patch=ns.min_dynamic_patch,
        max_dynamic_patch=ns.max_dynamic_patch,
        batch=ns.batch,
        concurrency=ns.concurrency,
        log_file=ns.log_file,
        images=tuple(ns.image),
    )


def extract_error_detail(resp: Optional[HttpResponse]) -> str:
    if resp is None:
        return "no response body"
    text = resp.text.strip()
    if not text:
        return resp.reason or "empty response"
    try:
        data = resp.json()
    except ValueError:
        return text[:200]

    if isinstance(data, dict):
        for key in ("error", "message", "msg"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return json.dumps(data, ensure_ascii=False)[:200]


def request_chat(args: CliArgs) -> HttpResponse:
    headers = {
        "Authorization": f"Bearer {args.token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    request = Request(
        args.url,
        data=json.dumps(build_body(args)).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        return HttpResponse(urlopen(request, timeout=args.timeout))
    except HTTPError as exc:
        error_response = HttpResponse(exc)
        try:
            detail = extract_error_detail(error_response)
        finally:
            error_response.close()
        raise CliError(f"HTTP {error_response.status_code}: {detail}") from exc
    except socket.timeout as exc:
        raise CliError(f"request timed out after {args.timeout} seconds") from exc
    except URLError as exc:
        if isinstance(exc.reason, socket.timeout):
            raise CliError(f"request timed out after {args.timeout} seconds") from exc
        raise CliError(f"request failed: {exc.reason}") from exc


def load_json(resp: HttpResponse) -> Any:
    try:
        return resp.json()
    except ValueError as exc:
        raise CliError(f"response is not valid JSON: {exc}") from exc


def render_output(resp: HttpResponse, args: CliArgs) -> str:
    payload = load_json(resp)
    if not isinstance(payload, dict):
        raise CliError("response JSON root is not an object")
    try:
        content = parse_response_content(payload)
    except CliError as exc:
        raise CliError(f"unexpected response structure: {exc}") from exc
    return strip_thinking(content)


def clone_for_single_image(args: CliArgs, image_source: str) -> CliArgs:
    return CliArgs(
        prompt=args.prompt,
        model=args.model,
        token=args.token,
        url=args.url,
        timeout=args.timeout,
        max_tokens=args.max_tokens,
        thinking=args.thinking,
        skip_special_tokens=args.skip_special_tokens,
        min_dynamic_patch=args.min_dynamic_patch,
        max_dynamic_patch=args.max_dynamic_patch,
        batch=False,
        concurrency=1,
        log_file=args.log_file,
        images=(image_source,),
    )


def run_single(args: CliArgs) -> str:
    resp = request_chat(args)
    try:
        return render_output(resp, args)
    finally:
        resp.close()


def run_batch(args: CliArgs) -> Dict[str, Any]:
    def worker(index_image: tuple[int, str]) -> Dict[str, Any]:
        index, image_source = index_image
        single_args = clone_for_single_image(args, image_source)
        try:
            output = run_single(single_args)
            return {
                "index": index,
                "image": image_source,
                "status": "ok",
                "output": output,
            }
        except CliError as exc:
            return {
                "index": index,
                "image": image_source,
                "status": "error",
                "error": str(exc),
            }

    image_items = list(enumerate(args.images, start=1))
    if args.concurrency == 1 or len(image_items) <= 1:
        results = [worker(item) for item in image_items]
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
            futures = [executor.submit(worker, item) for item in image_items]
            results = [future.result() for future in concurrent.futures.as_completed(futures)]
    results.sort(key=lambda item: int(item["index"]))
    return {"results": results}


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = None
    try:
        args = parse_args(argv)
        append_log(
            args.log_file,
            {
                "script": "qianfan_ocr_cli",
                "status": "started",
                "image_count": len(args.images),
                "images": list(args.images),
                "thinking": args.thinking,
                "skip_special_tokens": args.skip_special_tokens,
                "max_tokens": args.max_tokens,
                "min_dynamic_patch": args.min_dynamic_patch,
                "max_dynamic_patch": args.max_dynamic_patch,
                "batch": args.batch,
                "concurrency": args.concurrency,
            },
        )
        if args.batch:
            payload = run_batch(args)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            failed = [item for item in payload["results"] if item["status"] != "ok"]
            if failed:
                raise CliError(f"{len(failed)} batch item(s) failed")
        else:
            print(run_single(args))
        append_log(
            args.log_file,
            {
                "script": "qianfan_ocr_cli",
                "status": "succeeded",
                "image_count": len(args.images),
                "batch": args.batch,
            },
        )
        return 0
    except CliError as exc:
        append_log(
            getattr(args, "log_file", None),
            {
                "script": "qianfan_ocr_cli",
                "status": "failed",
                "error": str(exc),
            },
        )
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
