CREATE TABLE IF NOT EXISTS swe_asset_upload_record (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  file_name VARCHAR(512) NOT NULL COMMENT '上传文件名',
  file_size BIGINT NOT NULL COMMENT '文件大小（字节）',
  asset_path VARCHAR(512) NOT NULL COMMENT '文件存储路径',
  source_id VARCHAR(64) NULL COMMENT '来源标识',

  template_flag VARCHAR(64) NULL COMMENT '主模板标识',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  KEY idx_swe_asset_upload_record_source (source_id, created_at),
  KEY idx_swe_asset_upload_record_created (created_at),
  UNIQUE KEY uk_swe_asset_upload_record_file_name (file_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='模板上传记录';
