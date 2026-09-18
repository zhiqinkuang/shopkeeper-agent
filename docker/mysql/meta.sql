SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;
CREATE DATABASE meta DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
GRANT ALL PRIVILEGES ON meta.* TO 'didilili'@'%';

USE meta;

DROP TABLE IF EXISTS table_info;
CREATE TABLE table_info
(
    id          VARCHAR(64) PRIMARY KEY COMMENT '表编号',
    name        VARCHAR(128) COMMENT '表名称',
    role        VARCHAR(32) COMMENT '表类型(fact/dim)',
    description TEXT COMMENT '表描述'
);



DROP TABLE IF EXISTS column_info;
CREATE TABLE column_info
(
    id          VARCHAR(64) PRIMARY KEY COMMENT '列编号',
    name        VARCHAR(128) COMMENT '列名称',
    type        VARCHAR(64) COMMENT '数据类型',
    role        VARCHAR(32) COMMENT '列类型(primary_key,foreign_key,measure,dimension)',
    examples    JSON COMMENT '数据示例',
    description TEXT COMMENT '列描述',
    alias       JSON COMMENT '列别名',
    table_id    VARCHAR(64) COMMENT '所属表编号',
    CONSTRAINT fk_column_info_table
        FOREIGN KEY (table_id) REFERENCES table_info (id) ON DELETE CASCADE
);

DROP TABLE IF EXISTS metric_info;
CREATE TABLE metric_info
(
    id               VARCHAR(64) PRIMARY KEY COMMENT '指标编码',
    name             VARCHAR(128) COMMENT '指标名称',
    description      TEXT COMMENT '指标描述',
    relevant_columns JSON COMMENT '关联的列',
    alias            JSON COMMENT '指标别名',
    formula          TEXT NOT NULL COMMENT '指标计算公式'
);


DROP TABLE IF EXISTS column_metric;
CREATE TABLE column_metric
(
    column_id VARCHAR(64) COMMENT '列编号',
    metric_id VARCHAR(64) COMMENT '指标编号',
    PRIMARY KEY (column_id, metric_id),
    CONSTRAINT fk_column_metric_column
        FOREIGN KEY (column_id) REFERENCES column_info (id) ON DELETE CASCADE,
    CONSTRAINT fk_column_metric_metric
        FOREIGN KEY (metric_id) REFERENCES metric_info (id) ON DELETE CASCADE
);

DROP TABLE IF EXISTS query_audit;
CREATE TABLE query_audit
(
    id               VARCHAR(64) PRIMARY KEY COMMENT '审计编号',
    request_id       VARCHAR(64) COMMENT '请求编号',
    query            TEXT NOT NULL COMMENT '用户问题',
    sql_text         TEXT COMMENT '最终 SQL',
    execution_result JSON COMMENT '查询结果',
    answer           TEXT COMMENT '自然语言回答',
    error            TEXT COMMENT '错误信息',
    created_at       DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    INDEX idx_query_audit_request_id (request_id)
);

SET FOREIGN_KEY_CHECKS = 1;