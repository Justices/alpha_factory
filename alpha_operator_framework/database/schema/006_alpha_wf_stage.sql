-- Version 006: alpha_details 系统内工作流阶段 wf_stage。
-- 运行时实际迁移由 repository.py `_init_database()` 的 ALTER-guard 完成;
-- 本脚本与 002-005 一样是版本化文档。
ALTER TABLE alpha_details ADD COLUMN wf_stage TEXT NOT NULL DEFAULT 'pending_validation';
CREATE INDEX IF NOT EXISTS idx_detail_wf_stage ON alpha_details(wf_stage);
