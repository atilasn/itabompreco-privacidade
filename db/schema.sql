-- NeoVision AI — MySQL 8.x (opcional quando NEOVISION_DB=mysql; por defeito a API usa SQLite local)
-- Charset: utf8mb4

CREATE DATABASE IF NOT EXISTS neovision
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE neovision;

-- Usuários do desktop / app
CREATE TABLE IF NOT EXISTS users (
  id            BINARY(16) NOT NULL PRIMARY KEY,
  username      VARCHAR(64) NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  display_name  VARCHAR(128) NULL,
  role          ENUM('admin', 'operator', 'viewer') NOT NULL DEFAULT 'viewer',
  created_at    DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at    DATETIME(3) NULL ON UPDATE CURRENT_TIMESTAMP(3),
  UNIQUE KEY uq_users_username (username)
) ENGINE=InnoDB;

-- Câmeras / DVR descobertos ou cadastrados
CREATE TABLE IF NOT EXISTS cameras (
  id              BINARY(16) NOT NULL PRIMARY KEY,
  name            VARCHAR(128) NOT NULL,
  manufacturer    VARCHAR(64) NULL,
  model           VARCHAR(64) NULL,
  ip_address      VARCHAR(45) NOT NULL,
  http_port       INT UNSIGNED NULL,
  rtsp_url        VARCHAR(512) NULL,
  onvif_endpoint  VARCHAR(512) NULL,
  extras_json     JSON NULL,
  username        VARCHAR(128) NULL,
  password_enc    VARBINARY(512) NULL,
  is_enabled      TINYINT(1) NOT NULL DEFAULT 1,
  last_seen_at    DATETIME(3) NULL,
  offline_incidents INT UNSIGNED NOT NULL DEFAULT 0,
  last_rtsp_probe_ok TINYINT(1) NULL,
  monitor_hub_scope VARCHAR(16) NOT NULL DEFAULT 'local',
  created_at      DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at      DATETIME(3) NULL ON UPDATE CURRENT_TIMESTAMP(3),
  KEY ix_cameras_ip (ip_address)
) ENGINE=InnoDB;

-- Monitorização LAN (ping ICMP) — painel “Equipamentos · rede”
CREATE TABLE IF NOT EXISTS network_equipment_hosts (
  id                      BINARY(16) NOT NULL PRIMARY KEY,
  label                   VARCHAR(128) NOT NULL DEFAULT '',
  ip_address              VARCHAR(253) NOT NULL,
  poll_interval_seconds   INT UNSIGNED NOT NULL DEFAULT 60,
  is_enabled              TINYINT(1) NOT NULL DEFAULT 1,
  icon_kind               VARCHAR(32) NOT NULL DEFAULT 'generic',
  last_state              TINYINT(1) NULL,
  last_check_utc          DATETIME(3) NULL,
  state_since_utc         DATETIME(3) NULL,
  total_up_seconds        BIGINT UNSIGNED NOT NULL DEFAULT 0,
  total_down_seconds      BIGINT UNSIGNED NOT NULL DEFAULT 0,
  offline_incidents       INT UNSIGNED NOT NULL DEFAULT 0,
  monitor_hub_scope       VARCHAR(16) NOT NULL DEFAULT 'local',
  extras_json             TEXT NULL,
  created_at              DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at              DATETIME(3) NULL ON UPDATE CURRENT_TIMESTAMP(3),
  KEY ix_net_eq_ip (ip_address),
  KEY ix_net_eq_en (is_enabled)
) ENGINE=InnoDB;

-- Pessoas cadastradas (facial)
CREATE TABLE IF NOT EXISTS persons (
  id            BINARY(16) NOT NULL PRIMARY KEY,
  display_name  VARCHAR(128) NOT NULL,
  notes         VARCHAR(512) NULL,
  is_active     TINYINT(1) NOT NULL DEFAULT 1,
  created_at    DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at    DATETIME(3) NULL ON UPDATE CURRENT_TIMESTAMP(3)
) ENGINE=InnoDB;

-- Embeddings / referência facial (vetor serializado ou path)
CREATE TABLE IF NOT EXISTS face_embeddings (
  id          BINARY(16) NOT NULL PRIMARY KEY,
  person_id   BINARY(16) NOT NULL,
  source      ENUM('manual', 'import', 'capture') NOT NULL DEFAULT 'capture',
  embedding   BLOB NOT NULL,
  model_name  VARCHAR(64) NOT NULL,
  created_at  DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  CONSTRAINT fk_face_person FOREIGN KEY (person_id) REFERENCES persons(id) ON DELETE CASCADE,
  KEY ix_face_person (person_id)
) ENGINE=InnoDB;

-- Eventos do sistema (IA, automação, alarme)
CREATE TABLE IF NOT EXISTS events (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  event_type      VARCHAR(64) NOT NULL,
  severity        ENUM('info', 'warning', 'critical') NOT NULL DEFAULT 'info',
  camera_id       BINARY(16) NULL,
  person_id       BINARY(16) NULL,
  payload_json    JSON NULL,
  created_at      DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  KEY ix_events_type_time (event_type, created_at),
  KEY ix_events_camera (camera_id),
  CONSTRAINT fk_events_camera FOREIGN KEY (camera_id) REFERENCES cameras(id) ON DELETE SET NULL,
  CONSTRAINT fk_events_person FOREIGN KEY (person_id) REFERENCES persons(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- Logs operacionais (auditoria)
CREATE TABLE IF NOT EXISTS access_logs (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_id     BINARY(16) NULL,
  action      VARCHAR(128) NOT NULL,
  detail_json JSON NULL,
  ip_address  VARCHAR(45) NULL,
  created_at  DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  KEY ix_access_time (created_at),
  CONSTRAINT fk_access_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- Regras de automação (portão, alarme)
CREATE TABLE IF NOT EXISTS automation_rules (
  id            BINARY(16) NOT NULL PRIMARY KEY,
  name          VARCHAR(128) NOT NULL,
  is_enabled    TINYINT(1) NOT NULL DEFAULT 1,
  trigger_type  VARCHAR(64) NOT NULL,
  action_type   VARCHAR(64) NOT NULL,
  config_json   JSON NOT NULL,
  created_at    DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at    DATETIME(3) NULL ON UPDATE CURRENT_TIMESTAMP(3)
) ENGINE=InnoDB;

-- Notificações pendentes / histórico para app
CREATE TABLE IF NOT EXISTS notifications (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_id       BINARY(16) NULL,
  title         VARCHAR(256) NOT NULL,
  body          VARCHAR(1024) NULL,
  event_id      BIGINT UNSIGNED NULL,
  is_read       TINYINT(1) NOT NULL DEFAULT 0,
  created_at    DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  KEY ix_notif_user (user_id, created_at),
  CONSTRAINT fk_notif_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
  CONSTRAINT fk_notif_event FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE SET NULL
) ENGINE=InnoDB;
