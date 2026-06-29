#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""Send text messages and files to the elink report API."""

import argparse
import http.client
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse
from uuid import uuid4

import yaml


DEFAULT_CONFIG_PATH = "/app/config/config.yaml"
DEFAULT_BASE_URL = "http://10.120.182.54:9090"
DEFAULT_MESSAGE_PATH = "/api/report/sendMessage"
DEFAULT_FILE_PATH = "/api/report/sendFile"
EXCEL_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
SUCCESS_CODES = (None, 0, 200, 500, "0", "200", "500")


class ElinkClient:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        send_message_path: str = DEFAULT_MESSAGE_PATH,
        send_file_path: str = DEFAULT_FILE_PATH,
        timeout_seconds: int = 30,
        logger: Optional[logging.Logger] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.send_message_url = self._join_url(send_message_path)
        self.send_file_url = self._join_url(send_file_path)
        self.timeout_seconds = timeout_seconds
        self.logger = logger or logging.getLogger(__name__)

    def _join_url(self, path_or_url: str) -> str:
        if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
            return path_or_url
        return f"{self.base_url}/{path_or_url.lstrip('/')}"

    @classmethod
    def from_config(
        cls,
        config: Dict[str, Any],
        logger: Optional[logging.Logger] = None,
    ) -> "ElinkClient":
        elink_config = config.get("elink", {})
        return cls(
            base_url=elink_config.get("base_url", DEFAULT_BASE_URL),
            send_message_path=elink_config.get("send_message_path", DEFAULT_MESSAGE_PATH),
            send_file_path=elink_config.get("send_file_path", DEFAULT_FILE_PATH),
            timeout_seconds=int(elink_config.get("timeout_seconds", 30)),
            logger=logger,
        )

    def send_message(self, touser_id: str, content: str, message_type: int = 1) -> Dict[str, Any]:
        payload = {
            "touserId": str(touser_id),
            "content": content,
            "type": int(message_type),
        }
        self.logger.info("开始发送elink文本消息 | 接收方: %s | 类型: %s", touser_id, message_type)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return self._post(
            self.send_message_url,
            body=body,
            headers={"Content-Type": "application/json"},
            action_name="文本消息",
        )

    def send_file(self, file_path: str, touser_id: str, message_type: int = 1) -> Dict[str, Any]:
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        self.logger.info(
            "开始发送elink文件 | 文件: %s | 接收方: %s | 类型: %s",
            path,
            touser_id,
            message_type,
        )
        data = {
            "touserId": str(touser_id),
            "type": str(int(message_type)),
        }
        body, content_type = _build_multipart_body(
            fields=data,
            file_field="file",
            file_path=path,
            content_type=_guess_content_type(path),
        )
        return self._post(
            self.send_file_url,
            body=body,
            headers={"Content-Type": content_type},
            action_name="文件",
        )

    def _post(
        self,
        url: str,
        body: bytes,
        headers: Dict[str, str],
        action_name: str,
    ) -> Dict[str, Any]:
        headers = {
            "Accept": "*/*",
            "User-Agent": "ticket-review-scheduler/1.0",
            **headers,
        }
        parsed_url = urlparse(url)
        connection_cls = http.client.HTTPSConnection if parsed_url.scheme == "https" else http.client.HTTPConnection
        path = parsed_url.path or "/"
        if parsed_url.query:
            path = f"{path}?{parsed_url.query}"

        connection = connection_cls(parsed_url.hostname, parsed_url.port, timeout=self.timeout_seconds)
        try:
            connection.request("POST", path, body=body, headers=headers)
            response = connection.getresponse()
            status_code = response.status
            response_text = response.read().decode("utf-8", errors="replace")
        except OSError as e:
            raise RuntimeError(f"elink{action_name}发送失败: {e}") from e
        finally:
            connection.close()

        try:
            response_data = json.loads(response_text)
        except ValueError:
            response_data = {"raw": response_text}

        if status_code != 200:
            self.logger.error(
                "elink%s发送失败 | HTTP状态: %s | 返回: %s",
                action_name,
                status_code,
                response_text,
            )
            raise RuntimeError(f"elink{action_name}发送失败: HTTP {status_code}")

        code = response_data.get("code")
        if code not in SUCCESS_CODES:
            raise RuntimeError(f"elink{action_name}发送失败: {response_data}")

        self.logger.info("elink%s发送成功 | 返回: %s", action_name, response_data)
        return response_data


def _guess_content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".xlsx":
        return EXCEL_CONTENT_TYPE
    if suffix == ".xls":
        return "application/vnd.ms-excel"
    if suffix == ".txt":
        return "text/plain"
    return "application/octet-stream"


def _build_multipart_body(
    fields: Dict[str, str],
    file_field: str,
    file_path: Path,
    content_type: str,
) -> tuple:
    boundary = f"----ElinkFormBoundary{uuid4().hex}"
    body_parts = []

    file_name = file_path.name
    body_parts.extend(
        [
            f"--{boundary}\r\n".encode("utf-8"),
            (
                f'Content-Disposition: form-data; name="{file_field}"; '
                f'filename="{file_name}"\r\n'
            ).encode("utf-8"),
            f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"),
            file_path.read_bytes(),
            b"\r\n",
        ]
    )

    for key, value in fields.items():
        body_parts.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"),
                str(value).encode("utf-8"),
                b"\r\n",
            ]
        )

    body_parts.extend(
        [
            f"--{boundary}--\r\n".encode("utf-8"),
        ]
    )

    return b"".join(body_parts), f"multipart/form-data; boundary={boundary}"


def load_config(config_path: str) -> Dict[str, Any]:
    if not os.path.exists(config_path):
        return {}
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="发送文本消息或文件到elink接口")
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG_PATH,
        help="配置文件路径，默认读取容器内 /app/config/config.yaml",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    message_parser = subparsers.add_parser("send-message", help="发送文本消息")
    message_parser.add_argument("--touser-id", required=True, help="接收人或群组ID")
    message_parser.add_argument("--content", required=True, help="发送内容")
    message_parser.add_argument("--type", type=int, default=1, help="1发个人，2发群组")

    file_parser = subparsers.add_parser("send-file", help="发送文件")
    file_parser.add_argument("--touser-id", required=True, help="接收人或群组ID")
    file_parser.add_argument("--file-path", required=True, help="待发送文件路径")
    file_parser.add_argument("--type", type=int, default=1, help="1发个人，2发群组")

    return parser


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    args = build_arg_parser().parse_args()
    config = load_config(args.config)
    client = ElinkClient.from_config(config)

    if args.command == "send-message":
        try:
            result = client.send_message(args.touser_id, args.content, args.type)
        except Exception as e:
            print(f"发送失败: {e}", file=sys.stderr)
            raise SystemExit(1)
    else:
        try:
            result = client.send_file(args.file_path, args.touser_id, args.type)
        except Exception as e:
            print(f"发送失败: {e}", file=sys.stderr)
            raise SystemExit(1)

    print(result)


if __name__ == "__main__":
    main()
