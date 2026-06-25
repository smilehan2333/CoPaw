-- 技能注册表：存储 skill_id、cn_name 等字段
-- 用于跨系统同步和界面展示

CREATE TABLE IF NOT EXISTS swe_skills (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    skill_id VARCHAR(128) NOT NULL COMMENT '技能唯一标识符，跨租户共享',
    skill_name VARCHAR(128) NOT NULL COMMENT '技能目录名/运行时标识',
    cn_name VARCHAR(256) NOT NULL COMMENT '中文展示名',
    tenant_id VARCHAR(64) NOT NULL COMMENT '租户ID',
    tenant_name VARCHAR(256) DEFAULT '' COMMENT '租户名称',
    bbk_id VARCHAR(64) DEFAULT '' COMMENT 'BBK标识符',
    source VARCHAR(32) DEFAULT 'customized' COMMENT '来源：builtin/customized/marketplace',
    source_id VARCHAR(64) DEFAULT '' COMMENT '来源ID',
    enabled TINYINT(1) DEFAULT 0 COMMENT '是否启用',
    description TEXT COMMENT '技能描述',
    version_text VARCHAR(32) DEFAULT '1.0.0' COMMENT '版本号',
    signature VARCHAR(64) DEFAULT '' COMMENT '内容哈希',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_tenant_skill_name (tenant_id, skill_name),
    INDEX idx_skill_name_tenant_source (skill_name, tenant_id, source_id),
    INDEX idx_tenant_enabled (tenant_id, enabled),
    INDEX idx_bbk_id (bbk_id),
    INDEX idx_source (source)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='技能注册表';

-- 扩展追踪表：添加 skill_id 和 cn_name 字段
ALTER TABLE swe_tracing_spans
ADD COLUMN skill_id VARCHAR(128) DEFAULT '' COMMENT '技能唯一标识符' AFTER skill_name,
ADD COLUMN cn_name VARCHAR(256) DEFAULT '' COMMENT '技能中文展示名' AFTER skill_id;

-- 为新字段添加索引
CREATE INDEX idx_skill_id ON swe_tracing_spans(skill_id);