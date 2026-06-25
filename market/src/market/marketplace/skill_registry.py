# -*- coding: utf-8 -*-
"""技能注册表数据库操作.

隔离 swe_skills 表相关的数据库操作，便于统一管理和扩展。
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class SkillRegistry:
    """技能注册表数据库操作类."""

    def __init__(self, db):
        """初始化，接收数据库连接对象."""
        self.db = db

    def is_connected(self) -> bool:
        """检查数据库是否已连接."""
        return self.db.is_connected

    async def update_skill(
        self,
        user_id: str,
        skill_name: str,
        source_id: str = "",
        cn_name: str | None = None,
        version: str | None = None,
        enabled: bool | None = None,
    ) -> bool:
        """更新数据库 swe_skills 表中的技能信息.

        Args:
            user_id: 用户ID（租户ID）
            skill_name: 技能名
            source_id: 来源ID
            cn_name: 中文展示名（可选）
            version: 版本号（可选）
            enabled: 是否启用（可选）

        Returns:
            是否成功更新
        """
        if not self.is_connected():
            logger.warning("Database not connected, skip update swe_skills")
            return False

        try:
            # 构建更新字段
            update_fields = ["updated_at = CURRENT_TIMESTAMP"]
            params: list[Any] = []

            if cn_name:
                update_fields.append("cn_name = %s")
                params.append(cn_name)

            if version:
                update_fields.append("version_text = %s")
                params.append(version)

            if enabled is not None:
                update_fields.append("enabled = %s")
                params.append(enabled)

            params.extend([skill_name, user_id, source_id])

            sql = f"""
                UPDATE swe_skills
                SET {', '.join(update_fields)}
                WHERE skill_name = %s AND tenant_id = %s AND source_id = %s
            """
            await self.db.execute(sql, params)
            logger.info(
                "Updated swe_skills: skill_name=%s, tenant=%s, source_id=%s, cn_name=%s, version=%s, enabled=%s",
                skill_name,
                user_id,
                source_id,
                cn_name or "(unchanged)",
                version or "(unchanged)",
                enabled if enabled is not None else "(unchanged)",
            )
            return True
        except Exception as e:
            logger.warning("Failed to update swe_skills: %s", e)
            return False

    async def insert_skill(
        self,
        skill_id: str,
        skill_name: str,
        cn_name: str,
        tenant_id: str,
        tenant_name: str = "",
        bbk_id: str = "",
        source: str = "customized",
        source_id: str = "",
        enabled: bool = True,
        description: str = "",
        version_text: str = "1.0.0",
    ) -> bool:
        """插入或更新技能记录（两步操作：先查询再决定插入/更新）.

        按 skill_name + tenant_id + source_id 判断是否存在：
        - 存在：更新现有记录
        - 不存在：插入新记录

        Args:
            skill_id: 技能唯一标识符
            skill_name: 技能名
            cn_name: 中文展示名
            tenant_id: 租户ID
            tenant_name: 租户名称
            bbk_id: BBK标识
            source: 来源（builtin/customized/marketplace）
            source_id: 来源ID
            enabled: 是否启用
            description: 描述
            version_text: 版本号

        Returns:
            是否成功插入/更新
        """
        if not self.is_connected():
            logger.warning("Database not connected, skip insert swe_skills")
            return False

        try:
            # 第一步：查询是否存在（按 skill_name + tenant_id + source_id）
            existing = await self.db.fetch_one(
                """
                SELECT id, skill_id FROM swe_skills
                WHERE skill_name = %s AND tenant_id = %s AND source_id = %s
                """,
                (skill_name, tenant_id, source_id),
            )

            if existing:
                # 第二步：更新现有记录
                old_skill_id = existing.get("skill_id", "")
                await self.db.execute(
                    """
                    UPDATE swe_skills
                    SET skill_id = %s, cn_name = %s, source = %s,
                        source_id = %s, enabled = %s, description = %s,
                        version_text = %s, tenant_name = %s, bbk_id = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (
                        skill_id,
                        cn_name,
                        source,
                        source_id,
                        enabled,
                        description,
                        version_text,
                        tenant_name,
                        bbk_id,
                        existing.get("id"),
                    ),
                )
                logger.info(
                    "Updated swe_skills: skill_name=%s, tenant=%s, skill_id=%s -> %s, cn_name=%s",
                    skill_name,
                    tenant_id,
                    old_skill_id,
                    skill_id,
                    cn_name,
                )
            else:
                # 第二步：插入新记录
                await self.db.execute(
                    """
                    INSERT INTO swe_skills
                        (skill_id, skill_name, cn_name, tenant_id,
                         tenant_name, bbk_id, source, source_id, enabled,
                         description, version_text)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        skill_id,
                        skill_name,
                        cn_name,
                        tenant_id,
                        tenant_name,
                        bbk_id,
                        source,
                        source_id,
                        enabled,
                        description,
                        version_text,
                    ),
                )
                logger.info(
                    "Inserted swe_skills: skill_id=%s, skill_name=%s, tenant=%s, source_id=%s",
                    skill_id,
                    skill_name,
                    tenant_id,
                    source_id,
                )
            return True
        except Exception as e:
            logger.warning("Failed to insert/update swe_skills: %s", e)
            return False

    async def delete_skill(
        self,
        tenant_id: str,
        skill_name: str,
        source_id: str = "",
    ) -> bool:
        """删除技能记录.

        Args:
            tenant_id: 租户ID
            skill_name: 技能名
            source_id: 来源ID

        Returns:
            是否成功删除
        """
        if not self.is_connected():
            return False

        try:
            await self.db.execute(
                """
                DELETE FROM swe_skills
                WHERE skill_name = %s AND tenant_id = %s AND source_id = %s
                """,
                (skill_name, tenant_id, source_id),
            )
            logger.info(
                "Deleted swe_skills: skill_name=%s, tenant=%s, source_id=%s",
                skill_name,
                tenant_id,
                source_id,
            )
            return True
        except Exception as e:
            logger.warning("Failed to delete swe_skills: %s", e)
            return False

    async def upsert_skill_by_name(
        self,
        skill_id: str,
        skill_name: str,
        cn_name: str,
        tenant_id: str,
        tenant_name: str = "",
        bbk_id: str = "",
        source: str = "customized",
        source_id: str = "",
        enabled: bool = True,
        description: str = "",
        version_text: str = "1.0.0",
    ) -> bool:
        """按 skill_name + tenant_id + source_id 幂等插入或更新技能记录.

        处理逻辑：
        1. 先查询是否存在 skill_name + tenant_id + source_id 的记录
        2. 如果存在：更新 skill_id、cn_name 等字段
        3. 如果不存在：插入新记录

        Args:
            skill_id: 技能唯一标识符
            skill_name: 技能名
            cn_name: 中文展示名
            tenant_id: 租户ID
            tenant_name: 租户名称
            bbk_id: BBK标识
            source: 来源（builtin/customized/marketplace）
            source_id: 来源ID
            enabled: 是否启用
            description: 描述
            version_text: 版本号

        Returns:
            是否成功插入/更新
        """
        if not self.is_connected():
            logger.warning("Database not connected, skip upsert swe_skills")
            return False

        try:
            # 先查询是否存在（按 skill_name + tenant_id + source_id）
            existing = await self.db.fetch_one(
                """
                SELECT id, skill_id FROM swe_skills
                WHERE skill_name = %s AND tenant_id = %s AND source_id = %s
                """,
                (skill_name, tenant_id, source_id),
            )

            if existing:
                # 更新现有记录
                await self.db.execute(
                    """
                    UPDATE swe_skills
                    SET skill_id = %s, cn_name = %s, source = %s,
                        source_id = %s, enabled = %s, description = %s,
                        version_text = %s, tenant_name = %s, bbk_id = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (
                        skill_id,
                        cn_name,
                        source,
                        source_id,
                        enabled,
                        description,
                        version_text,
                        tenant_name,
                        bbk_id,
                        existing.get("id"),
                    ),
                )
                logger.info(
                    "Updated swe_skills: skill_name=%s, tenant=%s, skill_id=%s -> %s, cn_name=%s",
                    skill_name,
                    tenant_id,
                    existing.get("skill_id", ""),
                    skill_id,
                    cn_name,
                )
            else:
                # 插入新记录
                await self.db.execute(
                    """
                    INSERT INTO swe_skills
                        (skill_id, skill_name, cn_name, tenant_id,
                         tenant_name, bbk_id, source, source_id, enabled,
                         description, version_text)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        skill_id,
                        skill_name,
                        cn_name,
                        tenant_id,
                        tenant_name,
                        bbk_id,
                        source,
                        source_id,
                        enabled,
                        description,
                        version_text,
                    ),
                )
                logger.info(
                    "Inserted swe_skills: skill_id=%s, skill_name=%s, tenant=%s, source_id=%s",
                    skill_id,
                    skill_name,
                    tenant_id,
                    source_id,
                )
            return True
        except Exception as e:
            logger.warning("Failed to upsert swe_skills: %s", e)
            return False

    async def list_skills_for_init(
        self,
        tenant_id: str | None = None,
    ) -> list[dict]:
        """查询需要初始化 skill_id 或 cn_name 的技能记录.

        Args:
            tenant_id: 可选，指定租户ID，不传则查询所有

        Returns:
            技能记录列表，包含 skill_id, skill_name, cn_name, tenant_id 等字段
        """
        if not self.is_connected():
            return []

        try:
            if tenant_id:
                sql = """
                    SELECT skill_id, skill_name, cn_name, tenant_id,
                           tenant_name, bbk_id, source, source_id,
                           enabled, description, version_text
                    FROM swe_skills
                    WHERE tenant_id = %s
                """
                rows = await self.db.fetch_all(sql, (tenant_id,))
            else:
                sql = """
                    SELECT skill_id, skill_name, cn_name, tenant_id,
                           tenant_name, bbk_id, source, source_id,
                           enabled, description, version_text
                    FROM swe_skills
                """
                rows = await self.db.fetch_all(sql)
            return rows
        except Exception as e:
            logger.warning("Failed to list swe_skills: %s", e)
            return []

    async def update_skill_id_cn_name(
        self,
        tenant_id: str,
        skill_name: str,
        source_id: str,
        skill_id: str,
        cn_name: str,
    ) -> bool:
        """更新 swe_skills 表中的 skill_id 和 cn_name.

        Args:
            tenant_id: 租户ID
            skill_name: 技能名
            source_id: 来源ID
            skill_id: 技能唯一标识符
            cn_name: 中文展示名

        Returns:
            是否成功更新
        """
        if not self.is_connected():
            logger.warning("Database not connected, skip update swe_skills")
            return False

        try:
            await self.db.execute(
                """
                UPDATE swe_skills
                SET skill_id = %s, cn_name = %s, updated_at = CURRENT_TIMESTAMP
                WHERE skill_name = %s AND tenant_id = %s AND source_id = %s
                """,
                (skill_id, cn_name, skill_name, tenant_id, source_id),
            )
            logger.info(
                "Updated swe_skills skill_id/cn_name: skill_name=%s, tenant=%s, source_id=%s, skill_id=%s, cn_name=%s",
                skill_name,
                tenant_id,
                source_id,
                skill_id,
                cn_name,
            )
            return True
        except Exception as e:
            logger.warning("Failed to update swe_skills: %s", e)
            return False

    async def update_cn_name_by_skill_id(
        self,
        skill_id: str,
        tenant_id: str,
        cn_name: str,
    ) -> bool:
        """按 skill_id 更新 cn_name，只更新 marketplace 来源.

        用于市场技能中文名同步时，精准定位已分发用户的技能记录，
        避免误更新同名自建技能（skill_name 相同但 skill_id 不同）。

        Args:
            skill_id: 技能唯一标识符
            tenant_id: 租户ID
            cn_name: 新的中文展示名

        Returns:
            是否成功更新
        """
        if not self.is_connected():
            logger.warning("Database not connected, skip update swe_skills")
            return False

        try:
            await self.db.execute(
                """
                UPDATE swe_skills
                SET cn_name = %s, updated_at = CURRENT_TIMESTAMP
                WHERE skill_id = %s AND tenant_id = %s AND source LIKE 'marketplace%%'
                """,
                (cn_name, skill_id, tenant_id),
            )
            logger.info(
                "Updated swe_skills cn_name by skill_id: skill_id=%s, tenant=%s, cn_name=%s",
                skill_id,
                tenant_id,
                cn_name,
            )
            return True
        except Exception as e:
            logger.warning("Failed to update cn_name by skill_id: %s", e)
            return False

    async def list_unique_skills_by_source_id(
        self,
        source_id: str,
    ) -> list[dict]:
        """查询某个 source_id 的所有技能，按 skill_id 去重.

        Args:
            source_id: 来源ID

        Returns:
            技能列表，每个 skill_id 只返回一条记录，包含 skill_id、skill_name、cn_name
        """
        if not self.is_connected():
            return []

        try:
            rows = await self.db.fetch_all(
                """
                SELECT DISTINCT skill_id, skill_name, cn_name
                FROM swe_skills
                WHERE source_id = %s
                ORDER BY skill_id
                """,
                (source_id,),
            )
            logger.info(
                "Listed unique skills by source_id: source_id=%s, count=%d",
                source_id,
                len(rows),
            )
            return rows
        except Exception as e:
            logger.warning("Failed to list unique skills: %s", e)
            return []
