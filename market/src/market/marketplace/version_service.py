# -*- coding: utf-8 -*-
"""技能版本管理服务."""

from __future__ import annotations

import difflib
import hashlib
import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .fs import get_skill_dir, _atomic_write_json
from .version_models import (
    SkillVersion,
    VersionsManifest,
    VersionCompareResult,
    VersionDiffStats,
    VersionDiffFile,
    VersionSwitchResult,
    VersionDeleteResult,
)
from ..utils.skill_md import extract_version as _extract_version_md
from ..utils.version import bump_patch as _shared_bump_patch

logger = logging.getLogger(__name__)

# 忽略的文件（签名计算和复制时跳过）
_IGNORED_ARTIFACTS = {
    "__pycache__",
    "__MACOSX",
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
    ".git",
}

# 仅用于版本比对展示；不要用于签名、快照复制或版本详情文件树。
_COMPARE_EXCLUDED_FILES = {"skill.json"}


class SkillVersionService:
    """技能版本管理服务.

    管理市场技能的版本快照，支持创建、查询、切换、比对和删除版本。

    存储结构:
        <marketplace_root>/<source_id>/skill_versions/<item_id>/
        ├── versions.json
        ├── v2.3.0/
        │   ├── SKILL.md
        │   └── ...
        └── v2.2.0/
            └── ...
    """

    def __init__(self, marketplace_root: Path):
        self.marketplace_root = Path(marketplace_root)

    def create_version_snapshot(
        self,
        source_id: str,
        item_id: str,
        skill_dir: Path,
        description: str = "",
        creator: str = "",
        creator_name: str = "",
        current_market_version: Optional[str] = None,
        created_at: Optional[str] = None,
        source_user_id: str = "",
        source_user_name: str = "",
        source_user_version: str = "",
    ) -> SkillVersion:
        """创建新版本快照.

        版本号生成策略：
        1. 如果 SKILL.md 有 version 字段，直接使用
        2. 如果版本历史存在，接着最后版本递增
        3. 如果无版本历史且有 current_market_version，使用它
        4. 如果无版本历史且无 current_market_version，默认 1.0.0

        版本描述生成策略：
        1. 如果传入 description，使用传入值
        2. 如果是初始版本（无历史），描述为 "首次上传"
        3. 如果有历史版本，计算 diff 统计生成描述（如 "变更 3 个文件，新增 12 行"）

        Args:
            source_id: 来源 ID
            item_id: 条目 ID
            skill_dir: 当前技能文件目录
            description: 版本描述（可选，不传则自动生成）
            creator: 创建者 ID
            creator_name: 创建者名称
            current_market_version: 市场索引中的当前版本号（可选）
            created_at: 创建时间 ISO8601 格式（可选，用于历史技能初始化）

        Returns:
            创建的版本信息
        """
        # 加载版本清单
        manifest = self._load_versions_manifest(source_id, item_id)
        existing_ids = {v.version_id for v in manifest.versions}

        # 判断是否是初始版本
        is_initial = len(manifest.versions) == 0

        # 获取版本历史中的最新版本（用于递增和 diff 计算）
        last_version_from_history = ""
        last_version_signature = ""
        last_version_dir: Optional[Path] = None
        if manifest.versions:
            # 按创建时间排序，获取最新版本
            sorted_versions = sorted(
                manifest.versions,
                key=lambda v: v.created_at,
                reverse=True,
            )
            last_version_from_history = sorted_versions[0].version_id
            last_version_signature = sorted_versions[0].signature
            last_version_dir = self._get_version_dir(
                source_id,
                item_id,
                last_version_from_history,
            )

        # 先计算新内容签名（市场版本号生成依赖签名比对）
        new_signature = self._calculate_signature(skill_dir)

        # R3: 市场端版本号独立于 SKILL.md，由签名 + 历史决定
        version_id = self._derive_market_version_id(
            new_signature=new_signature,
            current_market_version=current_market_version,
            last_version_from_history=last_version_from_history,
            last_version_signature=last_version_signature,
            existing_ids=existing_ids,
        )

        # 确保版本号唯一，处理冲突情况
        if version_id in existing_ids:
            # 版本号已存在，检查签名是否相同
            existing_version_info = next(
                (v for v in manifest.versions if v.version_id == version_id),
                None,
            )
            if (
                existing_version_info
                and existing_version_info.signature == new_signature
            ):
                # R7: 同版本同内容 → 完全 no-op
                # 不创建快照、不修改 is_current、不更新 manifest
                logger.info(
                    "Version %s already exists with same content, skipping snapshot creation (R7 no-op)",
                    version_id,
                )
                return existing_version_info
            else:
                # 同版本不同内容 → 报错，要求调用方处理
                # 注意：F2 修订后，此分支只在历史 version_id 与 _bump_patch
                # 后的结果发生罕见碰撞时触发；publish_skill 上层会捕获 ValueError
                # 转 409 让前端可见。
                raise ValueError(
                    f"Version {version_id} already exists with different content. "
                    f"Please specify a new version or allow auto-bump.",
                )

        # 复用上面已计算的签名
        signature = new_signature

        # 复制文件到版本目录
        version_dir = self._get_version_dir(source_id, item_id, version_id)
        self._copy_skill_to_version(skill_dir, version_dir)

        # 自动生成版本描述（如果未传入）
        if not description:
            if is_initial:
                description = "首次上传"
            elif last_version_dir and last_version_dir.exists():
                # 计算与上一个版本的 diff 统计
                stats = self._compute_quick_diff_stats(
                    last_version_dir,
                    skill_dir,
                )
                if stats["changed_files"] == 0:
                    description = "无变更"
                else:
                    parts = [f"变更 {stats['changed_files']} 个文件"]
                    if stats["added_lines"] > 0:
                        parts.append(f"新增 {stats['added_lines']} 行")
                    if stats["deleted_lines"] > 0:
                        parts.append(f"删除 {stats['deleted_lines']} 行")
                    description = "，".join(parts)

        # 创建版本信息
        now = created_at or datetime.now(timezone.utc).isoformat()
        new_version = SkillVersion(
            version_id=version_id,
            created_at=now,
            created_by=creator,
            created_by_name=creator_name,
            description=description,
            signature=signature,
            is_current=True,
            is_initial=is_initial,
            source_user_id=source_user_id,
            source_user_name=source_user_name,
            source_user_version=source_user_version,
        )

        # 更新版本清单：将所有其他版本的 is_current 设为 False
        for v in manifest.versions:
            v.is_current = False
        manifest.versions.append(new_version)
        manifest.skill_name = self._get_skill_name(skill_dir)

        # 保存版本清单
        self._save_versions_manifest(source_id, item_id, manifest)

        logger.info(
            "Created version snapshot %s for skill %s",
            version_id,
            item_id,
        )

        return new_version

    def list_versions(
        self,
        source_id: str,
        item_id: str,
    ) -> dict[str, Any]:
        """获取版本历史列表.

        Args:
            source_id: 来源 ID
            item_id: 条目 ID

        Returns:
            包含 skill_name 和 versions 的字典，版本按创建时间倒序排列
        """
        manifest = self._load_versions_manifest(source_id, item_id)
        # 按创建时间倒序
        versions = sorted(
            manifest.versions,
            key=lambda v: v.created_at,
            reverse=True,
        )
        return {
            "skill_name": manifest.skill_name,
            "versions": [v.model_dump() for v in versions],
        }

    def get_version_detail(
        self,
        source_id: str,
        item_id: str,
        version_id: str,
    ) -> dict[str, Any]:
        """获取单个版本详情.

        Args:
            source_id: 来源 ID
            item_id: 条目 ID
            version_id: 版本 ID

        Returns:
            版本详情，包含文件树
        """
        manifest = self._load_versions_manifest(source_id, item_id)
        version_info = next(
            (v for v in manifest.versions if v.version_id == version_id),
            None,
        )
        if version_info is None:
            raise ValueError(f"Version {version_id} not found")

        version_dir = self._get_version_dir(source_id, item_id, version_id)
        if not version_dir.exists():
            raise ValueError(f"Version directory {version_id} not found")

        # 构建文件树
        file_tree = self._build_file_tree(version_dir)

        return {
            "version_info": version_info.model_dump(),
            "file_tree": file_tree,
        }

    def switch_version(
        self,
        source_id: str,
        item_id: str,
        target_version_id: str,
        current_skill_dir: Path,
    ) -> VersionSwitchResult:
        """切换到指定版本.

        将目标版本的文件复制到技能主目录，更新版本清单中的 is_current 标识。

        Args:
            source_id: 来源 ID
            item_id: 条目 ID
            target_version_id: 目标版本 ID
            current_skill_dir: 当前技能文件目录（用于覆盖）

        Returns:
            切换结果
        """
        manifest = self._load_versions_manifest(source_id, item_id)

        # 找到目标版本
        target_version = next(
            (
                v
                for v in manifest.versions
                if v.version_id == target_version_id
            ),
            None,
        )
        if target_version is None:
            return VersionSwitchResult(
                success=False,
                message=f"Version {target_version_id} not found",
            )

        # 找到当前版本
        current_version = next(
            (v for v in manifest.versions if v.is_current),
            None,
        )
        previous_version_id = (
            current_version.version_id if current_version else ""
        )

        # 检查目标版本目录存在
        target_dir = self._get_version_dir(
            source_id,
            item_id,
            target_version_id,
        )
        if not target_dir.exists():
            return VersionSwitchResult(
                success=False,
                message=f"Version directory {target_version_id} not found",
            )

        # 复制目标版本文件到技能主目录
        self._copy_skill_to_version(target_dir, current_skill_dir)

        # 更新版本清单中的 is_current 标识
        for v in manifest.versions:
            v.is_current = v.version_id == target_version_id

        self._save_versions_manifest(source_id, item_id, manifest)

        logger.info(
            "Switched skill %s from %s to %s",
            item_id,
            previous_version_id,
            target_version_id,
        )

        return VersionSwitchResult(
            success=True,
            previous_version=previous_version_id,
            current_version=target_version_id,
            message=f"Switched to version {target_version_id}",
        )

    def compare_versions(
        self,
        source_id: str,
        item_id: str,
        base_version_id: str,
        target_version_id: str,
    ) -> VersionCompareResult:
        """比对两个版本.

        对比文件列表和每个文件的内容差异，返回 Diff 详情。
        包含所有文件（变更文件和未变更文件），用于前端展示完整目录树。

        Args:
            source_id: 来源 ID
            item_id: 条目 ID
            base_version_id: 基准版本 ID
            target_version_id: 目标版本 ID

        Returns:
            比对结果，包含变更统计和所有文件信息
        """
        base_dir = self._get_version_dir(source_id, item_id, base_version_id)
        target_dir = self._get_version_dir(
            source_id,
            item_id,
            target_version_id,
        )

        if not base_dir.exists():
            raise ValueError(f"Base version {base_version_id} not found")
        if not target_dir.exists():
            raise ValueError(f"Target version {target_version_id} not found")

        # 收集两个版本的文件；skill.json 是系统元数据，版本比对展示中不显示。
        base_files = (
            self._collect_skill_files(base_dir) - _COMPARE_EXCLUDED_FILES
        )
        target_files = (
            self._collect_skill_files(target_dir) - _COMPARE_EXCLUDED_FILES
        )

        # 计算差异
        added_files = target_files - base_files
        deleted_files = base_files - target_files
        common_files = base_files & target_files

        files_diff: list[VersionDiffFile] = []
        total_added = 0
        total_deleted = 0
        changed_files_count = 0

        # 处理新增文件
        for f in sorted(added_files):
            target_path = target_dir / f
            target_lines = self._read_file_lines(target_path)
            added_count = len(target_lines)
            diff_text = self._generate_diff_for_new_file(target_path)
            modified_content = self._read_file_content(target_path)
            files_diff.append(
                VersionDiffFile(
                    path=f,
                    added_lines=added_count,
                    deleted_lines=0,
                    diff=diff_text,
                    original_content="",  # 新文件，旧版本不存在
                    modified_content=modified_content,
                ),
            )
            total_added += added_count
            changed_files_count += 1

        # 处理删除文件
        for f in sorted(deleted_files):
            base_path = base_dir / f
            base_lines = self._read_file_lines(base_path)
            deleted_count = len(base_lines)
            diff_text = self._generate_diff_for_deleted_file(base_path)
            original_content = self._read_file_content(base_path)
            files_diff.append(
                VersionDiffFile(
                    path=f,
                    added_lines=0,
                    deleted_lines=deleted_count,
                    diff=diff_text,
                    original_content=original_content,
                    modified_content="",  # 文件已删除，新版本不存在
                ),
            )
            total_deleted += deleted_count
            changed_files_count += 1

        # 处理公共文件（分为修改和未修改）
        for f in sorted(common_files):
            base_path = base_dir / f
            target_path = target_dir / f
            diff_text, added, deleted = self._compute_file_diff(
                base_path,
                target_path,
            )
            original_content = self._read_file_content(base_path)
            modified_content = self._read_file_content(target_path)

            if diff_text:  # 有差异
                files_diff.append(
                    VersionDiffFile(
                        path=f,
                        added_lines=added,
                        deleted_lines=deleted,
                        diff=diff_text,
                        original_content=original_content,
                        modified_content=modified_content,
                    ),
                )
                total_added += added
                total_deleted += deleted
                changed_files_count += 1
            else:  # 无差异（未变更文件）
                files_diff.append(
                    VersionDiffFile(
                        path=f,
                        added_lines=0,
                        deleted_lines=0,
                        diff="",  # 无差异
                        original_content=original_content,
                        modified_content=modified_content,
                    ),
                )

        return VersionCompareResult(
            base_version=base_version_id,
            target_version=target_version_id,
            stats=VersionDiffStats(
                added_lines=total_added,
                deleted_lines=total_deleted,
                changed_files=changed_files_count,
            ),
            files=files_diff,
        )

    def initialize_version(
        self,
        source_id: str,
        item_id: str,
        skill_dir: Path,
        creator: str = "",
        description: str = "初始化版本",
        current_market_version: Optional[str] = None,
        created_at: Optional[str] = None,
    ) -> SkillVersion:
        """为历史技能初始化第一个版本.

        仅对没有版本历史的技能生效，将当前状态创建为初始版本快照。

        Args:
            source_id: 来源 ID
            item_id: 条目 ID
            skill_dir: 当前技能文件目录
            creator: 创建者名称（复用技能原始数据）
            description: 版本描述
            current_market_version: 市场索引中的当前版本号（可选）
            created_at: 创建时间 ISO8601 格式（复用技能原始数据，可选）

        Returns:
            创建的初始版本信息

        Raises:
            ValueError: 如果技能已有版本历史
        """
        # 检查是否已有版本历史
        manifest = self._load_versions_manifest(source_id, item_id)
        if manifest.versions:
            raise ValueError(
                f"Skill {item_id} already has version history, "
                f"cannot initialize. Current versions: {len(manifest.versions)}",
            )

        # 使用 create_version_snapshot 创建第一个版本
        # 该方法会自动设置 is_initial=True 和 is_current=True
        return self.create_version_snapshot(
            source_id=source_id,
            item_id=item_id,
            skill_dir=skill_dir,
            description=description,
            creator=creator,
            current_market_version=current_market_version,
            created_at=created_at,
        )

    def delete_version(
        self,
        source_id: str,
        item_id: str,
        version_id: str,
    ) -> VersionDeleteResult:
        """删除指定版本.

        不允许删除当前版本。

        Args:
            source_id: 来源 ID
            item_id: 条目 ID
            version_id: 要删除的版本 ID

        Returns:
            是否删除成功
        """
        manifest = self._load_versions_manifest(source_id, item_id)

        # 找到要删除的版本
        target_version = next(
            (v for v in manifest.versions if v.version_id == version_id),
            None,
        )
        if target_version is None:
            return VersionDeleteResult(
                success=False,
                message=f"Version {version_id} not found",
            )

        # 禁止删除当前版本
        if target_version.is_current:
            return VersionDeleteResult(
                success=False,
                message="Cannot delete current version",
            )

        # 禁止删除初始版本（与 MCP 行为对称，避免破坏版本血脉）
        if target_version.is_initial:
            return VersionDeleteResult(
                success=False,
                message="Cannot delete initial version",
            )

        # 删除版本目录
        version_dir = self._get_version_dir(source_id, item_id, version_id)
        if version_dir.exists():
            shutil.rmtree(version_dir)

        # 从清单中移除
        manifest.versions = [
            v for v in manifest.versions if v.version_id != version_id
        ]
        self._save_versions_manifest(source_id, item_id, manifest)

        logger.info("Deleted version %s for skill %s", version_id, item_id)

        return VersionDeleteResult(
            success=True,
            deleted_version=version_id,
            message=f"Version {version_id} deleted",
        )

    # === 内部方法 ===

    def _get_version_root(
        self,
        source_id: str,
        item_id: str,
    ) -> Path:
        """获取版本根目录路径."""
        return self.marketplace_root / source_id / "skill_versions" / item_id

    def _get_version_dir(
        self,
        source_id: str,
        item_id: str,
        version_id: str,
    ) -> Path:
        """获取指定版本的目录路径."""
        return self._get_version_root(source_id, item_id) / version_id

    def _get_versions_json_path(
        self,
        source_id: str,
        item_id: str,
    ) -> Path:
        """获取版本清单文件路径."""
        return self._get_version_root(source_id, item_id) / "versions.json"

    def _load_versions_manifest(
        self,
        source_id: str,
        item_id: str,
    ) -> VersionsManifest:
        """加载版本清单文件."""
        path = self._get_versions_json_path(source_id, item_id)
        if not path.exists():
            return VersionsManifest(skill_name="", versions=[])
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return VersionsManifest(**data)
        except (json.JSONDecodeError, KeyError):
            return VersionsManifest(skill_name="", versions=[])

    def _save_versions_manifest(
        self,
        source_id: str,
        item_id: str,
        manifest: VersionsManifest,
    ) -> None:
        """保存版本清单文件."""
        path = self._get_versions_json_path(source_id, item_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(path, manifest.model_dump())

    def _derive_market_version_id(
        self,
        new_signature: str,
        current_market_version: Optional[str],
        last_version_from_history: str,
        last_version_signature: str,
        existing_ids: set[str],
    ) -> str:
        """决定本次快照的市场端 version_id（R3 隔离 + R2 自动递增）.

        优先级（不再读取 SKILL.md 的 version 字段，市场版本号完全独立于用户工作区）：

        1. 没有历史 → 用 current_market_version 或 1.0.0 作为首版
        2. 有历史 + 内容签名等于历史最新版 → 复用历史 version_id
           （R7 的 no-op 由调用方继续处理）
        3. 有历史 + 内容签名不同 → 在历史最新版上 _bump_version 直到不撞 existing_ids
        """
        # 1. 无历史 → 首版
        if not last_version_from_history:
            return current_market_version or "1.0.0"

        # 2. 内容未变 → 复用最近一次的 version_id（让上层走 R7 no-op）
        if last_version_signature and new_signature == last_version_signature:
            return last_version_from_history

        # 3. 内容变了 → 自动递增，并避开历史已有的 version_id
        candidate = self._bump_version(last_version_from_history)
        # 极小概率撞车（人工 switch_version 后回到旧版再编辑）：继续 bump
        # 上限 100 次，避免极端情况下死循环
        for _ in range(100):
            if candidate not in existing_ids:
                return candidate
            candidate = self._bump_version(candidate)
        return candidate

    def _extract_version_from_skill(
        self,
        skill_dir: Path,
        current_market_version: Optional[str] = None,
        last_version_from_history: Optional[str] = None,
    ) -> str:
        """[Deprecated] 旧版本号生成接口，保留作为静态工具.

        已不在 create_version_snapshot 主流程中使用——由 _derive_market_version_id
        取代。仅保留供潜在外部调用方读取 SKILL.md 中的版本号字符串。
        """
        skill_md_path = skill_dir / "SKILL.md"
        if skill_md_path.exists():
            version = self._extract_version_from_frontmatter(
                skill_md_path.read_text(encoding="utf-8"),
            )
            if version:
                return version
        if current_market_version:
            return current_market_version
        if last_version_from_history:
            return self._bump_version(last_version_from_history)
        return "1.0.0"

    def _bump_version(self, version: str) -> str:
        """递增版本号的 patch 部分（委托共享工具）."""
        return _shared_bump_patch(version)

    def _extract_version_from_frontmatter(
        self,
        md_content: str,
    ) -> str:
        """从 SKILL.md frontmatter 中提取 version（委托共享工具）."""
        return _extract_version_md(md_content)

    @staticmethod
    def _extract_version_from_frontmatter_static(
        md_content: str,
    ) -> str:
        """从 SKILL.md frontmatter 中提取 version（静态方法，供外部调用）."""
        return _extract_version_md(md_content)

    def _calculate_signature(
        self,
        skill_dir: Path,
    ) -> str:
        """计算技能目录内容签名.

        对文本文件（.md / .json / .yaml / .yml / .txt / .toml）统一换行符
        为 LF 后再计算，避免因 write_text 在 Windows 上产生 CRLF 而导致
        内容相同但签名不同（跨路径 R7 no-op 失效）。
        """
        _TEXT_EXTENSIONS = frozenset(
            {
                ".md",
                ".json",
                ".yaml",
                ".yml",
                ".txt",
                ".toml",
            },
        )
        digest = hashlib.sha256()
        for path in sorted(skill_dir.rglob("*")):
            if path.is_file() and not self._is_ignored(path):
                rel = path.relative_to(skill_dir)
                digest.update(str(rel).encode("utf-8"))
                if path.suffix.lower() in _TEXT_EXTENSIONS:
                    # 文本文件：统一换行符为 LF
                    try:
                        content = path.read_text(encoding="utf-8")
                        digest.update(
                            content.replace("\r\n", "\n").encode("utf-8"),
                        )
                    except (UnicodeDecodeError, OSError):
                        # 编码异常时回退到原始字节
                        digest.update(path.read_bytes())
                else:
                    digest.update(path.read_bytes())
        return digest.hexdigest()

    def _is_ignored(
        self,
        path: Path,
    ) -> bool:
        """检查是否是忽略的文件."""
        return bool(_IGNORED_ARTIFACTS & set(path.parts))

    def _copy_skill_to_version(
        self,
        source_dir: Path,
        target_dir: Path,
    ) -> None:
        """复制技能文件到版本目录."""

        def _ignore(_dir: str, names: list[str]) -> set[str]:
            return {name for name in names if name in _IGNORED_ARTIFACTS}

        if target_dir.exists():
            shutil.rmtree(target_dir)
        shutil.copytree(source_dir, target_dir, ignore=_ignore)

    def _get_skill_name(
        self,
        skill_dir: Path,
    ) -> str:
        """从 SKILL.md 获取技能名称."""
        skill_md_path = skill_dir / "SKILL.md"
        if skill_md_path.exists():
            name = self._extract_name_from_frontmatter(
                skill_md_path.read_text(encoding="utf-8"),
            )
            if name:
                return name
        return skill_dir.name

    def _extract_name_from_frontmatter(
        self,
        md_content: str,
    ) -> str:
        """从 SKILL.md frontmatter 中提取 name."""
        if not md_content.startswith("---"):
            return ""
        try:
            end_idx = md_content.index("---", 3)
            fm_text = md_content[3:end_idx].strip()
        except ValueError:
            return ""

        for line in fm_text.split("\n"):
            if ":" in line:
                key, val = line.split(":", 1)
                key = key.strip().lower()
                val = val.strip()
                if key == "name" and val:
                    # 移除引号
                    if val.startswith('"') and val.endswith('"'):
                        val = val[1:-1]
                    elif val.startswith("'") and val.endswith("'"):
                        val = val[1:-1]
                    return val
        return ""

    def _build_file_tree(
        self,
        root: Path,
    ) -> list[dict[str, Any]]:
        """构建文件树列表."""
        if not root.exists():
            return []

        def build_tree(path: Path) -> dict[str, Any]:
            relative = path.relative_to(root).as_posix()
            if path.is_file():
                return {
                    "name": path.name,
                    "type": "file",
                    "path": relative,
                }
            children = []
            for child in sorted(path.iterdir()):
                if (
                    child.name.startswith(".")
                    or child.name in _IGNORED_ARTIFACTS
                ):
                    continue
                children.append(build_tree(child))
            return {
                "name": path.name,
                "type": "directory",
                "path": relative,
                "children": children,
            }

        items = sorted(root.iterdir())
        return [
            build_tree(item)
            for item in items
            if not item.name.startswith(".")
            and item.name not in _IGNORED_ARTIFACTS
        ]

    def _collect_skill_files(
        self,
        skill_dir: Path,
    ) -> set[str]:
        """收集技能目录中的所有文件路径."""
        files: set[str] = set()
        for path in skill_dir.rglob("*"):
            if path.is_file() and not self._is_ignored(path):
                rel = path.relative_to(skill_dir).as_posix()
                files.add(rel)
        return files

    def _read_file_lines(
        self,
        path: Path,
    ) -> list[str]:
        """读取文件内容为行列表."""
        try:
            content = path.read_text(encoding="utf-8")
            return content.splitlines(keepends=True)
        except (UnicodeDecodeError, OSError):
            return []

    def _read_file_content(
        self,
        path: Path,
    ) -> str:
        """读取文件完整内容."""
        try:
            return path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            return ""

    def _compute_file_diff(
        self,
        base_path: Path,
        target_path: Path,
    ) -> tuple[str, int, int]:
        """计算两个文件的差异.

        Returns:
            (diff_text, added_lines, deleted_lines)
        """
        base_lines = self._read_file_lines(base_path)
        target_lines = self._read_file_lines(target_path)

        # 使用 difflib 生成 unified diff
        diff = difflib.unified_diff(
            base_lines,
            target_lines,
            fromfile=f"a/{base_path.name}",
            tofile=f"b/{target_path.name}",
        )

        diff_text = "".join(diff)

        # 计算行数变化
        added = 0
        deleted = 0
        for line in diff_text.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                added += 1
            elif line.startswith("-") and not line.startswith("---"):
                deleted += 1

        return diff_text, added, deleted

    def _compute_quick_diff_stats(
        self,
        base_dir: Path,
        target_dir: Path,
    ) -> dict[str, int]:
        """快速计算两个目录的 diff 统计（用于版本描述生成）.

        Returns:
            {"changed_files": int, "added_lines": int, "deleted_lines": int}
        """
        base_files = (
            self._collect_skill_files(base_dir) - _COMPARE_EXCLUDED_FILES
        )
        target_files = (
            self._collect_skill_files(target_dir) - _COMPARE_EXCLUDED_FILES
        )

        added_files = target_files - base_files
        deleted_files = base_files - target_files
        common_files = base_files & target_files

        changed_files = 0
        total_added = 0
        total_deleted = 0

        # 新增文件
        for f in added_files:
            target_path = target_dir / f
            if target_path.is_file():
                lines = self._read_file_lines(target_path)
                total_added += len(lines)
                changed_files += 1

        # 删除文件
        for f in deleted_files:
            base_path = base_dir / f
            if base_path.is_file():
                lines = self._read_file_lines(base_path)
                total_deleted += len(lines)
                changed_files += 1

        # 修改文件
        for f in common_files:
            base_path = base_dir / f
            target_path = target_dir / f
            if base_path.is_file() and target_path.is_file():
                _, added, deleted = self._compute_file_diff(
                    base_path,
                    target_path,
                )
                if added > 0 or deleted > 0:
                    total_added += added
                    total_deleted += deleted
                    changed_files += 1

        return {
            "changed_files": changed_files,
            "added_lines": total_added,
            "deleted_lines": total_deleted,
        }

    def _generate_diff_for_new_file(
        self,
        path: Path,
    ) -> str:
        """生成新文件的 diff（全为新增行）."""
        lines = self._read_file_lines(path)
        diff_lines = [
            "--- /dev/null",
            f"+++ b/{path.name}",
        ]
        for line in lines:
            diff_lines.append(f"+{line}")
        return "\n".join(diff_lines)

    def _generate_diff_for_deleted_file(
        self,
        path: Path,
    ) -> str:
        """生成删除文件的 diff（全为删除行）."""
        lines = self._read_file_lines(path)
        diff_lines = [
            f"--- a/{path.name}",
            "+++ /dev/null",
        ]
        for line in lines:
            diff_lines.append(f"-{line}")
        return "\n".join(diff_lines)
