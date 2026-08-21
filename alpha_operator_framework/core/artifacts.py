"""事件溯源研究内核 — 不可变内容寻址工件库 (Content-Addressed Artifact Store).

所有 AST 树、配置快照、回测日度收益矩阵、验证报告均以不可变 SHA256 存入，
保证任一时点的实验均可 100% 幂等重放。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Union
import numpy as np


@dataclass(frozen=True)
class ArtifactMetadata:
    """工件元数据."""

    content_hash: str
    content_type: str  # json / text / matrix / binary
    size_bytes: int
    created_at: str


class ArtifactStore:
    """基于 SHA-256 的不可变内容寻址存储器."""

    def __init__(
        self,
        root_dir: Optional[Union[str, Path]] = None,
        storage_dir: Optional[Union[str, Path]] = None,
    ):
        dir_p = storage_dir or root_dir
        self.root_dir = Path(dir_p) if dir_p else None
        self._memory_store: Dict[str, bytes] = {}
        self._metadata_store: Dict[str, ArtifactMetadata] = {}

        if self.root_dir:
            self.root_dir.mkdir(parents=True, exist_ok=True)

    def put_json(self, data: Any) -> str:
        """存储 JSON 结构体并返回 SHA256 哈希."""
        raw_bytes = json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return self._put_raw(raw_bytes, content_type="json")

    def put_text(self, text: str) -> str:
        """存储纯文本/表达式/代码并返回 SHA256 哈希."""
        raw_bytes = text.encode("utf-8")
        return self._put_raw(raw_bytes, content_type="text")

    def put_matrix(self, matrix: Union[np.ndarray, Sequence[Any]]) -> str:
        """存储收益率/暴露/截面矩阵并返回 SHA256 哈希."""
        arr = np.asarray(matrix, dtype=float)
        raw_bytes = arr.tobytes()
        return self._put_raw(raw_bytes, content_type="matrix", extra={"shape": arr.shape})

    def _put_raw(self, raw_bytes: bytes, content_type: str, extra: Optional[Dict[str, Any]] = None) -> str:
        content_hash = hashlib.sha256(raw_bytes).hexdigest()

        # 1. 存入内存缓存
        self._memory_store[content_hash] = raw_bytes

        # 2. 若配置了磁盘目录，落盘持久化 (按前2位分桶避免单目录膨胀)
        if self.root_dir:
            bucket_dir = self.root_dir / content_hash[:2]
            bucket_dir.mkdir(parents=True, exist_ok=True)
            blob_path = bucket_dir / content_hash[2:]
            if not blob_path.exists():
                blob_path.write_bytes(raw_bytes)

        return content_hash

    def get_json(self, content_hash: str) -> Any:
        """根据 Hash 读取 JSON 对象."""
        raw_bytes = self.get_raw(content_hash)
        return json.loads(raw_bytes.decode("utf-8"))

    def get_text(self, content_hash: str) -> str:
        """根据 Hash 读取文本字符串."""
        raw_bytes = self.get_raw(content_hash)
        return raw_bytes.decode("utf-8")

    def get_raw(self, content_hash: str) -> bytes:
        """根据 Hash 读取原始二进制字节."""
        if content_hash in self._memory_store:
            return self._memory_store[content_hash]

        if self.root_dir:
            blob_path = self.root_dir / content_hash[:2] / content_hash[2:]
            if blob_path.exists():
                data = blob_path.read_bytes()
                self._memory_store[content_hash] = data
                return data

        raise KeyError(f"Artifact not found: {content_hash}")

    def has(self, content_hash: str) -> bool:
        """判断工件是否存在."""
        if content_hash in self._memory_store:
            return True
        if self.root_dir:
            blob_path = self.root_dir / content_hash[:2] / content_hash[2:]
            return blob_path.exists()
        return False
