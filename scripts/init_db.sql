-- MySQL 建表脚本（项目一）
-- 用法：mysql -u root -p < scripts/init_db.sql
CREATE DATABASE IF NOT EXISTS store_agent DEFAULT CHARSET utf8mb4;
USE store_agent;

CREATE TABLE IF NOT EXISTS repair_orders (
    order_no     VARCHAR(32) PRIMARY KEY,
    store_id     VARCHAR(16) NOT NULL,
    device       VARCHAR(64) NOT NULL,
    problem_desc VARCHAR(1024),
    priority     VARCHAR(16) DEFAULT '普通',
    status       VARCHAR(16) DEFAULT '已受理',
    sla          VARCHAR(64),
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
) DEFAULT CHARSET = utf8mb4;

CREATE TABLE IF NOT EXISTS chat_logs (
    id         BIGINT AUTO_INCREMENT PRIMARY KEY,
    session_id VARCHAR(64) NOT NULL,
    user_id    VARCHAR(64) DEFAULT '',
    store_id   VARCHAR(16) DEFAULT '',
    query      TEXT,
    intent     VARCHAR(32) DEFAULT '',
    answer     TEXT,
    handoff    TINYINT DEFAULT 0,
    latency_ms INT DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    KEY idx_session (session_id),
    KEY idx_created (created_at)
) DEFAULT CHARSET = utf8mb4;
