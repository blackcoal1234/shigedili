-- ============================================================
-- 诗行万里 · 主题版数据库 schema
-- 基础诗词六表 + 创作时空/行旅/情感/证据扩展表
-- ============================================================
CREATE DATABASE IF NOT EXISTS shixing_wanli
    DEFAULT CHARACTER SET utf8mb4
    DEFAULT COLLATE utf8mb4_unicode_ci;

USE shixing_wanli;

DROP TABLE IF EXISTS t_poem_line_note;
DROP TABLE IF EXISTS t_poem_background;
DROP TABLE IF EXISTS t_claim_evidence;
DROP TABLE IF EXISTS t_image_emotion;
DROP TABLE IF EXISTS t_poem_emotion;
DROP TABLE IF EXISTS t_emotion;
DROP TABLE IF EXISTS t_poem_context;
DROP TABLE IF EXISTS t_journey_stop;
DROP TABLE IF EXISTS t_life_event;
DROP TABLE IF EXISTS t_source;
DROP TABLE IF EXISTS t_poem_image;
DROP TABLE IF EXISTS t_poem_place;
DROP TABLE IF EXISTS t_image;
DROP TABLE IF EXISTS t_place;
DROP TABLE IF EXISTS t_poem;
DROP TABLE IF EXISTS t_poet;

-- ---------- 诗人 ----------
CREATE TABLE IF NOT EXISTS t_poet (
    poet_id    INT          AUTO_INCREMENT PRIMARY KEY                 COMMENT '诗人ID',
    name       VARCHAR(32)  NOT NULL UNIQUE                            COMMENT '诗人姓名',
    dynasty    VARCHAR(16)  NOT NULL                                   COMMENT '朝代',
    school     VARCHAR(32)                                             COMMENT '旧版流派兼容字段',
    poem_count INT          DEFAULT 0                                  COMMENT '入库作品数',
    INDEX idx_dynasty(dynasty),
    INDEX idx_school(school)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='诗人表';

-- ---------- 诗作 ----------
CREATE TABLE IF NOT EXISTS t_poem (
    poem_id        INT          AUTO_INCREMENT PRIMARY KEY,
    poet_id        INT          NOT NULL,
    title          VARCHAR(128) NOT NULL,
    body           TEXT         NOT NULL,
    body_len       INT          DEFAULT 0,
    sentiment      DECIMAL(4,2) DEFAULT 0                              COMMENT '旧版基础情感值',
    season         VARCHAR(8)                                          COMMENT '旧版季节兼容字段',
    source_site    VARCHAR(32),
    source_url     VARCHAR(512),
    source_poem_id VARCHAR(128),
    body_hash      CHAR(64)     NOT NULL                               COMMENT '正文SHA-256',
    crawled_at     DATETIME,
    UNIQUE KEY uk_poet_body_hash(poet_id, body_hash),
    INDEX idx_poet(poet_id),
    INDEX idx_source_poem(source_poem_id),
    CONSTRAINT fk_poem_poet FOREIGN KEY (poet_id)
        REFERENCES t_poet(poet_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='诗作表';

-- ---------- 地名 ----------
CREATE TABLE IF NOT EXISTS t_place (
    place_id   INT          AUTO_INCREMENT PRIMARY KEY,
    alias      VARCHAR(32)  NOT NULL UNIQUE                            COMMENT '古名',
    modern     VARCHAR(32)  NOT NULL                                   COMMENT '今地名',
    province   VARCHAR(16),
    lon        DECIMAL(9,6),
    lat        DECIMAL(9,6),
    note       VARCHAR(128),
    INDEX idx_modern(modern)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='诗中地名词典';

-- ---------- 意象 ----------
CREATE TABLE IF NOT EXISTS t_image (
    image_id   INT          AUTO_INCREMENT PRIMARY KEY,
    word       VARCHAR(16)  NOT NULL UNIQUE,
    category   VARCHAR(16)  NOT NULL,
    sentiment  DECIMAL(4,2) DEFAULT 0                                  COMMENT '旧版固定情感值',
    INDEX idx_category(category)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='意象词典';

-- ---------- 诗-提及地 多对多 ----------
CREATE TABLE IF NOT EXISTS t_poem_place (
    poem_id  INT NOT NULL,
    place_id INT NOT NULL,
    freq     INT DEFAULT 1,
    PRIMARY KEY (poem_id, place_id),
    CONSTRAINT fk_pp_poem FOREIGN KEY (poem_id)
        REFERENCES t_poem(poem_id) ON DELETE CASCADE,
    CONSTRAINT fk_pp_place FOREIGN KEY (place_id)
        REFERENCES t_place(place_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='诗中提及地点，不代表创作地或到访地';

-- ---------- 诗-意象 多对多 ----------
CREATE TABLE IF NOT EXISTS t_poem_image (
    poem_id  INT NOT NULL,
    image_id INT NOT NULL,
    freq     INT DEFAULT 1,
    PRIMARY KEY (poem_id, image_id),
    CONSTRAINT fk_pi_poem FOREIGN KEY (poem_id)
        REFERENCES t_poem(poem_id) ON DELETE CASCADE,
    CONSTRAINT fk_pi_image FOREIGN KEY (image_id)
        REFERENCES t_image(image_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='诗作-意象关联';

-- ---------- 资料来源 ----------
CREATE TABLE IF NOT EXISTS t_source (
    source_id    INT          AUTO_INCREMENT PRIMARY KEY,
    source_name  VARCHAR(255) NOT NULL,
    source_url   VARCHAR(768),
    source_type  VARCHAR(32)  DEFAULT 'web',
    citation     TEXT,
    source_note  TEXT,
    source_grade CHAR(1)      DEFAULT 'C',
    access_level VARCHAR(32)  DEFAULT 'public_web',
    license_note TEXT,
    content_hash CHAR(64),
    source_version VARCHAR(128),
    accessed_at  DATE,
    UNIQUE KEY uk_source_url(source_url(255))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='资料来源';

-- ---------- 诗人生平事件 ----------
CREATE TABLE IF NOT EXISTS t_life_event (
    event_id         INT          AUTO_INCREMENT PRIMARY KEY,
    poet_id          INT          NOT NULL,
    event_title      VARCHAR(255) NOT NULL,
    event_type       VARCHAR(32)  NOT NULL,
    year_start       SMALLINT,
    year_end         SMALLINT,
    historical_place VARCHAR(255),
    modern_city      VARCHAR(64),
    province         VARCHAR(32),
    description      TEXT,
    source_id        INT,
    fact_grade       CHAR(1)      DEFAULT 'C',
    review_status    VARCHAR(16)  DEFAULT 'pending',
    INDEX idx_event_poet_year(poet_id, year_start),
    CONSTRAINT fk_event_poet FOREIGN KEY (poet_id)
        REFERENCES t_poet(poet_id) ON DELETE CASCADE,
    CONSTRAINT fk_event_source FOREIGN KEY (source_id)
        REFERENCES t_source(source_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='诗人生平事件';

-- ---------- 诗人到访/停留地点 ----------
CREATE TABLE IF NOT EXISTS t_journey_stop (
    stop_id          INT          AUTO_INCREMENT PRIMARY KEY,
    poet_id          INT          NOT NULL,
    event_id         INT,
    event_title      VARCHAR(255) NOT NULL,
    year_start       SMALLINT,
    year_end         SMALLINT,
    historical_place VARCHAR(255) NOT NULL,
    modern_city      VARCHAR(64)  NOT NULL,
    province         VARCHAR(32),
    lon              DECIMAL(9,6),
    lat              DECIMAL(9,6),
    life_context     TEXT,
    related_poems    TEXT                                             COMMENT 'JSON标题数组',
    source_id        INT,
    fact_grade       CHAR(1)      DEFAULT 'C',
    confidence       DECIMAL(4,3) DEFAULT 0.500,
    review_status    VARCHAR(16)  DEFAULT 'pending',
    INDEX idx_stop_poet_year(poet_id, year_start),
    INDEX idx_stop_city(modern_city),
    CONSTRAINT fk_stop_poet FOREIGN KEY (poet_id)
        REFERENCES t_poet(poet_id) ON DELETE CASCADE,
    CONSTRAINT fk_stop_event FOREIGN KEY (event_id)
        REFERENCES t_life_event(event_id) ON DELETE SET NULL,
    CONSTRAINT fk_stop_source FOREIGN KEY (source_id)
        REFERENCES t_source(source_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='诗人行旅节点';

-- ---------- 作品创作时空与背景 ----------
CREATE TABLE IF NOT EXISTS t_poem_context (
    context_id       INT          AUTO_INCREMENT PRIMARY KEY,
    poem_id          INT          NOT NULL,
    year_start       SMALLINT,
    year_end         SMALLINT,
    historical_place VARCHAR(255),
    modern_city      VARCHAR(64),
    province         VARCHAR(32),
    lon              DECIMAL(9,6),
    lat              DECIMAL(9,6),
    context_note     TEXT,
    source_id        INT,
    fact_grade       CHAR(1)      DEFAULT 'C',
    confidence       DECIMAL(4,3) DEFAULT 0.500,
    review_status    VARCHAR(16)  DEFAULT 'pending',
    UNIQUE KEY uk_poem_context_source(poem_id, source_id),
    INDEX idx_context_year_city(year_start, modern_city),
    CONSTRAINT fk_context_poem FOREIGN KEY (poem_id)
        REFERENCES t_poem(poem_id) ON DELETE CASCADE,
    CONSTRAINT fk_context_source FOREIGN KEY (source_id)
        REFERENCES t_source(source_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='作品创作时间地点与背景';

-- ---------- 审核后富背景与逐句译注 ----------
CREATE TABLE IF NOT EXISTS t_poem_background (
    background_id       INT          AUTO_INCREMENT PRIMARY KEY,
    poem_id             INT          NOT NULL,
    background_summary  TEXT,
    story_summary       TEXT,
    historical_context  LONGTEXT     COMMENT 'JSON数组，仅存项目审核后的摘要',
    controversy_note    TEXT,
    publication_ready   TINYINT(1)   DEFAULT 0,
    review_status       VARCHAR(16)  DEFAULT 'pending',
    reviewers           LONGTEXT     COMMENT 'JSON审核人数组',
    reviewed_at         DATETIME,
    export_method       VARCHAR(64),
    UNIQUE KEY uk_poem_background(poem_id),
    CONSTRAINT fk_background_poem FOREIGN KEY (poem_id)
        REFERENCES t_poem(poem_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='审核后作品背景主数据';

CREATE TABLE IF NOT EXISTS t_poem_line_note (
    line_note_id      INT          AUTO_INCREMENT PRIMARY KEY,
    poem_id           INT          NOT NULL,
    line_no           SMALLINT     NOT NULL,
    original_text     TEXT,
    translation_text  TEXT,
    annotations       LONGTEXT     COMMENT 'JSON注释数组，项目整理',
    evidence_ids      LONGTEXT     COMMENT 'JSON候选ID数组',
    review_status     VARCHAR(16)  DEFAULT 'pending',
    reviewed_at       DATETIME,
    UNIQUE KEY uk_poem_line_note(poem_id, line_no),
    CONSTRAINT fk_line_note_poem FOREIGN KEY (poem_id)
        REFERENCES t_poem(poem_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='审核后逐句译注';

-- ---------- 多标签情感 ----------
CREATE TABLE IF NOT EXISTS t_emotion (
    emotion_id   INT          AUTO_INCREMENT PRIMARY KEY,
    label        VARCHAR(32)  NOT NULL UNIQUE,
    description  VARCHAR(255)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='情感标签词典';

CREATE TABLE IF NOT EXISTS t_poem_emotion (
    poem_id       INT          NOT NULL,
    emotion_id    INT          NOT NULL,
    score         DECIMAL(5,4) DEFAULT 0,
    evidence_line VARCHAR(500),
    method        VARCHAR(64)  NOT NULL DEFAULT 'rule_context_v1',
    confidence    DECIMAL(4,3) DEFAULT 0.500,
    review_status VARCHAR(16)  DEFAULT 'candidate',
    PRIMARY KEY (poem_id, emotion_id, method),
    CONSTRAINT fk_pe_poem FOREIGN KEY (poem_id)
        REFERENCES t_poem(poem_id) ON DELETE CASCADE,
    CONSTRAINT fk_pe_emotion FOREIGN KEY (emotion_id)
        REFERENCES t_emotion(emotion_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='诗词多标签文本情感';

CREATE TABLE IF NOT EXISTS t_image_emotion (
    image_emotion_id INT          AUTO_INCREMENT PRIMARY KEY,
    poem_id          INT          NOT NULL,
    image_id         INT          NOT NULL,
    emotion_id       INT          NOT NULL,
    function_label   VARCHAR(64),
    evidence_line    VARCHAR(500),
    method           VARCHAR(64)  NOT NULL DEFAULT 'rule_context_v1',
    confidence       DECIMAL(4,3) DEFAULT 0.500,
    review_status    VARCHAR(16)  DEFAULT 'candidate',
    INDEX idx_ie_image_poem(image_id, poem_id),
    CONSTRAINT fk_ie_poem FOREIGN KEY (poem_id)
        REFERENCES t_poem(poem_id) ON DELETE CASCADE,
    CONSTRAINT fk_ie_image FOREIGN KEY (image_id)
        REFERENCES t_image(image_id) ON DELETE CASCADE,
    CONSTRAINT fk_ie_emotion FOREIGN KEY (emotion_id)
        REFERENCES t_emotion(emotion_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='具体语境中的意象情感与功能';

-- ---------- 可追溯事实与证据 ----------
CREATE TABLE IF NOT EXISTS t_claim_evidence (
    claim_id       INT          AUTO_INCREMENT PRIMARY KEY,
    candidate_id   CHAR(64),
    claim_type     VARCHAR(32)  NOT NULL,
    subject_type   VARCHAR(32)  NOT NULL,
    subject_id     INT,
    predicate_name VARCHAR(64)  NOT NULL,
    object_text    TEXT         NOT NULL,
    source_id      INT,
    source_locator VARCHAR(512),
    evidence_text  TEXT,
    fact_grade     CHAR(1)      DEFAULT 'C',
    confidence     DECIMAL(4,3) DEFAULT 0.500,
    review_status  VARCHAR(16)  DEFAULT 'pending',
    extraction_method VARCHAR(64),
    model_id       VARCHAR(128),
    prompt_version VARCHAR(64),
    reviewer       VARCHAR(128),
    reviewed_at    DATETIME,
    created_at     TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_claim_candidate(candidate_id),
    INDEX idx_claim_subject(subject_type, subject_id),
    CONSTRAINT fk_claim_source FOREIGN KEY (source_id)
        REFERENCES t_source(source_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='事实或文学解释的证据链';
