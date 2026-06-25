-- -*- coding: utf-8 -*-
-- Migration: Add skill_id and skill_cn_name to swe_tracing_spans table
-- Description: 添加 skill_id 和 skill_cn_name 列到 swe_tracing_spans 表，
--              用于记录技能唯一标识符和中文展示名
-- Date: 2026-06-23

-- ============================================================
-- Migration 1: Add skill_id column
-- ============================================================
-- 技能唯一标识符，用于精确关联技能记录
ALTER TABLE `swe_tracing_spans`
ADD COLUMN `skill_id` VARCHAR(128) DEFAULT NULL COMMENT '技能唯一标识符，格式：customized_{user_id}_{skill_name} 或 {item_id}'
AFTER `skill_name`;

-- ============================================================
-- Migration 2: Add skill_cn_name column
-- ============================================================
-- 技能中文展示名，用于前端展示
ALTER TABLE `swe_tracing_spans`
ADD COLUMN `skill_cn_name` VARCHAR(256) DEFAULT NULL COMMENT '技能中文展示名'
AFTER `skill_id`;

-- ============================================================
-- Migration 3: Add index for skill_id
-- ============================================================
-- 添加索引便于按 skill_id 查询
ALTER TABLE `swe_tracing_spans`
ADD INDEX `idx_skill_id` (`skill_id`);

-- ============================================================
-- Verification
-- ============================================================
SHOW FULL COLUMNS FROM `swe_tracing_spans` WHERE Field IN ('skill_id', 'skill_cn_name');
SHOW INDEX FROM `swe_tracing_spans` WHERE Key_name = 'idx_skill_id';