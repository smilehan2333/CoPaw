-- 持续治理管理侧数据库读模型。

CREATE TABLE IF NOT EXISTS `swe_continuous_governance_records` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    `source_id` VARCHAR(128) NOT NULL COMMENT '来源系统标识',
    `target_user_id` VARCHAR(128) NOT NULL COMMENT '被治理用户标识',
    `target_agent_id` VARCHAR(128) NOT NULL DEFAULT 'default' COMMENT '被治理工作区 Agent 标识',
    `record_id` VARCHAR(128) NOT NULL COMMENT 'workspace dream 记录标识',
    `target_user_name` VARCHAR(255) DEFAULT NULL COMMENT '被治理用户名称',
    `bbk_id` VARCHAR(255) DEFAULT NULL COMMENT '被治理用户所属 BBK 标识',
    `occurred_at` VARCHAR(64) NOT NULL COMMENT '治理执行时间',
    `trigger_type` VARCHAR(64) NOT NULL COMMENT '触发方式，例如 manual 或 cron',
    `status` VARCHAR(64) NOT NULL COMMENT '治理执行状态',
    `model_used` VARCHAR(255) DEFAULT NULL COMMENT '本次治理使用的模型',
    `input_tokens` INT NOT NULL DEFAULT 0 COMMENT '输入 token 数',
    `output_tokens` INT NOT NULL DEFAULT 0 COMMENT '输出 token 数',
    `files_optimized_json` JSON NOT NULL COMMENT '优化文件列表 JSON',
    `total_size_saved` BIGINT NOT NULL DEFAULT 0 COMMENT '累计节省字节数',
    `total_files_changed` INT NOT NULL DEFAULT 0 COMMENT '变更文件数量',
    `duration_ms` BIGINT NOT NULL DEFAULT 0 COMMENT '执行耗时毫秒数',
    `summary` TEXT COMMENT '治理结果摘要',
    `error_text` TEXT COMMENT '失败错误信息',
    `rollback_timestamp` VARCHAR(64) DEFAULT NULL COMMENT '回滚时间',
    `rollback_files_json` JSON NOT NULL COMMENT '回滚文件列表 JSON',
    `raw_record_json` JSON NOT NULL COMMENT '原始 workspace 记录 JSON',
    `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_cg_record_identity` (
        `source_id`, `target_user_id`, `target_agent_id`, `record_id`
    ),
    KEY `idx_cg_records_source_time` (`source_id`, `occurred_at`),
    KEY `idx_cg_records_source_user` (`source_id`, `target_user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='持续治理执行记录读模型';

CREATE TABLE IF NOT EXISTS `swe_file_governance_archive_items` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    `source_id` VARCHAR(128) NOT NULL COMMENT '来源系统标识',
    `target_user_id` VARCHAR(128) NOT NULL COMMENT '被治理用户标识',
    `target_agent_id` VARCHAR(128) NOT NULL DEFAULT 'default' COMMENT '被治理工作区 Agent 标识',
    `archive_item_id` VARCHAR(128) NOT NULL COMMENT '归档条目标识',
    `original_path` TEXT NOT NULL COMMENT '归档前 workspace 相对路径',
    `archive_path` TEXT NOT NULL COMMENT '归档后 workspace 相对路径',
    `size_bytes` BIGINT NOT NULL DEFAULT 0 COMMENT '文件字节数',
    `mtime` VARCHAR(64) NOT NULL COMMENT '文件修改时间',
    `archived_at` VARCHAR(64) NOT NULL COMMENT '归档时间',
    `archived_by` VARCHAR(255) NOT NULL COMMENT '归档操作者',
    `archive_reason` VARCHAR(255) NOT NULL COMMENT '归档原因',
    `expired` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否已超过归档保留期',
    `raw_item_json` JSON NOT NULL COMMENT '原始归档条目 JSON',
    `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_fg_archive_identity` (
        `source_id`, `target_user_id`, `target_agent_id`, `archive_item_id`
    ),
    KEY `idx_fg_archive_source_time` (`source_id`, `archived_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='文件治理归档条目读模型';

CREATE TABLE IF NOT EXISTS `swe_file_governance_protected_files` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    `source_id` VARCHAR(128) NOT NULL COMMENT '来源系统标识',
    `target_user_id` VARCHAR(128) NOT NULL COMMENT '被治理用户标识',
    `target_agent_id` VARCHAR(128) NOT NULL DEFAULT 'default' COMMENT '被治理工作区 Agent 标识',
    `path` VARCHAR(384) NOT NULL COMMENT '受保护文件 workspace 相对路径',
    `protected_at` VARCHAR(64) NOT NULL COMMENT '加入保护名单时间',
    `protected_by` VARCHAR(255) NOT NULL COMMENT '保护操作者',
    `reason` VARCHAR(255) NOT NULL COMMENT '保护原因',
    `exists_flag` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '文件当前是否存在',
    `size_bytes` BIGINT DEFAULT NULL COMMENT '文件当前字节数',
    `mtime` VARCHAR(64) DEFAULT NULL COMMENT '文件当前修改时间',
    `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_fg_protected_identity` (
        `source_id`, `target_user_id`, `target_agent_id`, `path`
    ),
    KEY `idx_fg_protected_source` (`source_id`, `target_user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='文件治理保护文件读模型';

CREATE TABLE IF NOT EXISTS `swe_file_governance_cleanup_audits` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    `event_id` VARCHAR(128) NOT NULL COMMENT '清理审计事件标识',
    `occurred_at` VARCHAR(64) NOT NULL COMMENT '清理发生时间',
    `operation` VARCHAR(128) NOT NULL COMMENT '清理操作类型',
    `status` VARCHAR(64) NOT NULL COMMENT '清理操作状态',
    `actor_user_id` VARCHAR(255) NOT NULL COMMENT '操作人用户标识',
    `actor_role` VARCHAR(64) NOT NULL COMMENT '操作人角色',
    `source_id` VARCHAR(128) NOT NULL COMMENT '来源系统标识',
    `source_name` VARCHAR(255) DEFAULT NULL COMMENT '来源系统名称',
    `target_user_id` VARCHAR(128) NOT NULL COMMENT '被治理用户标识',
    `target_agent_id` VARCHAR(128) NOT NULL DEFAULT 'default' COMMENT '被治理工作区 Agent 标识',
    `scope` VARCHAR(128) NOT NULL COMMENT '清理范围',
    `files_count` INT NOT NULL DEFAULT 0 COMMENT '清理文件数量',
    `total_size_bytes` BIGINT NOT NULL DEFAULT 0 COMMENT '清理释放字节数',
    `reason` VARCHAR(255) NOT NULL COMMENT '清理原因',
    `error_text` TEXT COMMENT '清理失败错误信息',
    `raw_audit_json` JSON NOT NULL COMMENT '原始清理审计 JSON',
    `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_fg_cleanup_audit_event` (`source_id`, `event_id`),
    KEY `idx_fg_cleanup_source_time` (`source_id`, `occurred_at`),
    KEY `idx_fg_cleanup_source_user` (`source_id`, `target_user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='文件治理清理审计读模型';

CREATE TABLE IF NOT EXISTS `swe_continuous_governance_reconcile_health` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    `source_id` VARCHAR(128) NOT NULL COMMENT '来源系统标识',
    `target_user_id` VARCHAR(128) NOT NULL COMMENT '被治理用户标识',
    `target_agent_id` VARCHAR(128) NOT NULL DEFAULT 'default' COMMENT '被治理工作区 Agent 标识',
    `entity_type` VARCHAR(128) NOT NULL COMMENT '待对账实体类型',
    `entity_id` VARCHAR(128) NOT NULL COMMENT '待对账实体标识',
    `status` VARCHAR(64) NOT NULL COMMENT '对账状态',
    `reason` VARCHAR(255) NOT NULL COMMENT '进入对账队列原因',
    `error_text` TEXT COMMENT '最近一次写入或对账错误',
    `payload_json` JSON NOT NULL COMMENT '对账回放所需载荷 JSON',
    `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_cg_health_entity` (
        `source_id`, `target_user_id`, `target_agent_id`,
        `entity_type`, `entity_id`
    ),
    KEY `idx_cg_health_source_status` (`source_id`, `status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='持续治理读模型对账健康状态';
