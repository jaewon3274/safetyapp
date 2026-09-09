"""
Smart DMS - SQLite 데이터베이스 초기화 및 시드 데이터
"""
import sqlite3
import os
import json
from datetime import datetime
from werkzeug.security import generate_password_hash

DB_PATH = os.path.join(os.path.dirname(__file__), 'smart_dms.db')

ADMIN_PASSWORD = '240124!'


def get_db():
    """DB 연결 반환"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _migrate(conn):
    """기존 DB에 새 컬럼/테이블 추가 (멱등)"""
    c = conn.cursor()

    # users 테이블 신규 컬럼 추가
    existing_cols = {row[1] for row in c.execute("PRAGMA table_info(users)").fetchall()}
    if 'password_hash' not in existing_cols:
        c.execute("ALTER TABLE users ADD COLUMN password_hash TEXT NOT NULL DEFAULT ''")
    if 'status' not in existing_cols:
        c.execute("ALTER TABLE users ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
    if 'team' not in existing_cols:
        c.execute("ALTER TABLE users ADD COLUMN team TEXT NOT NULL DEFAULT ''")

    # 관리자: login_id를 'safety'로 변경 + 비밀번호 설정
    admin = c.execute("SELECT id, email, password_hash FROM users WHERE role='admin' LIMIT 1").fetchone()
    if admin:
        if admin['email'] != 'safety':
            c.execute("UPDATE users SET email='safety' WHERE role='admin'")
        if not admin['password_hash']:
            c.execute("UPDATE users SET password_hash=? WHERE role='admin'",
                      (generate_password_hash(ADMIN_PASSWORD),))

    # 직원: 패스워드 미설정 계정에 기본 비밀번호 '0000' 부여
    DEFAULT_PW = generate_password_hash('0000')
    c.execute(
        "UPDATE users SET password_hash=? WHERE role='employee' AND (password_hash='' OR password_hash IS NULL)",
        (DEFAULT_PW,)
    )

    # pending_users 테이블 생성 (password_hash 포함)
    c.execute("""
        CREATE TABLE IF NOT EXISTS pending_users (
            id            TEXT PRIMARY KEY,
            name          TEXT NOT NULL,
            department    TEXT NOT NULL DEFAULT '',
            team          TEXT NOT NULL DEFAULT '',
            password_hash TEXT NOT NULL DEFAULT '',
            status        TEXT NOT NULL DEFAULT 'pending',
            created_at    TEXT NOT NULL,
            reviewed_by   TEXT DEFAULT '',
            reviewed_at   TEXT DEFAULT ''
        )
    """)
    # 기존 pending_users에 password_hash 컬럼 없으면 추가
    p_cols = {row[1] for row in c.execute("PRAGMA table_info(pending_users)").fetchall()}
    if 'password_hash' not in p_cols:
        c.execute("ALTER TABLE pending_users ADD COLUMN password_hash TEXT NOT NULL DEFAULT ''")

    # ── 데이터 복구: status 컬럼에 비밀번호 해시가 들어간 잘못된 레코드 수정 ──
    # 이전 마이그레이션에서 password_hash 컬럼이 없었을 때 INSERT된 데이터가
    # 컬럼 shift 되어 status에 scrypt 해시값이 저장된 버그를 자동 복구합니다.
    bad_rows = c.execute(
        "SELECT id, status FROM pending_users WHERE status LIKE 'scrypt:%' OR (status != 'pending' AND status != 'approved' AND status != 'rejected')"
    ).fetchall()
    for row in bad_rows:
        # status에 들어간 해시를 password_hash로 이동하고 status를 'pending'으로 복구
        c.execute(
            "UPDATE pending_users SET password_hash=status, status='pending' WHERE id=?",
            (row[0],)
        )


    # user_site_assignments 테이블 (멱등)
    c.execute("""
        CREATE TABLE IF NOT EXISTS user_site_assignments (
            id          TEXT PRIMARY KEY,
            user_id     TEXT NOT NULL,
            project_id  TEXT NOT NULL,
            assigned_by TEXT NOT NULL DEFAULT '',
            assigned_at TEXT NOT NULL,
            UNIQUE(user_id, project_id)
        )
    """)

    # projects 테이블 신규 컬럼 추가 (기존 DB 호환)
    proj_cols = {row[1] for row in c.execute("PRAGMA table_info(projects)").fetchall()}
    if 'extra_notes' not in proj_cols:
        c.execute("ALTER TABLE projects ADD COLUMN extra_notes TEXT DEFAULT ''")
    if 'site_manager' not in proj_cols:
        c.execute("ALTER TABLE projects ADD COLUMN site_manager TEXT DEFAULT ''")
    if 'safety_manager' not in proj_cols:
        c.execute("ALTER TABLE projects ADD COLUMN safety_manager TEXT DEFAULT ''")

    # 단순화 작업계획서 테이블
    c.execute("""
        CREATE TABLE IF NOT EXISTS workplans (
            id           TEXT PRIMARY KEY,
            project_id   TEXT,
            work_date    TEXT NOT NULL DEFAULT '',
            work_content TEXT NOT NULL DEFAULT '',
            manager_name TEXT NOT NULL DEFAULT '',
            status       TEXT NOT NULL DEFAULT 'planned',
            creator_id   TEXT DEFAULT '',
            created_at   TEXT NOT NULL
        )
    """)

    # 공지사항 테이블
    c.execute("""
        CREATE TABLE IF NOT EXISTS notices (
            id           TEXT PRIMARY KEY,
            title        TEXT NOT NULL,
            content      TEXT NOT NULL DEFAULT '',
            file_name    TEXT NOT NULL DEFAULT '',
            file_path    TEXT NOT NULL DEFAULT '',
            author_name  TEXT NOT NULL DEFAULT '',
            author_id    TEXT NOT NULL DEFAULT '',
            created_at   TEXT NOT NULL
        )
    """)

    # workers 테이블 신규 컬럼 추가 (hire_date, notes)
    wrk_cols = {row[1] for row in c.execute("PRAGMA table_info(workers)").fetchall()}
    if 'hire_date' not in wrk_cols:
        c.execute("ALTER TABLE workers ADD COLUMN hire_date TEXT DEFAULT ''")
    if 'notes' not in wrk_cols:
        c.execute("ALTER TABLE workers ADD COLUMN notes TEXT DEFAULT ''")

    # workplans 테이블 image_path 컬럼 추가
    wp_cols = {row[1] for row in c.execute("PRAGMA table_info(workplans)").fetchall()}
    if 'image_path' not in wp_cols:
        c.execute("ALTER TABLE workplans ADD COLUMN image_path TEXT DEFAULT ''")

    # tbm_logs 테이블 image_path 컬럼 추가
    tbm_cols = {row[1] for row in c.execute("PRAGMA table_info(tbm_logs)").fetchall()}
    if 'image_path' not in tbm_cols:
        c.execute("ALTER TABLE tbm_logs ADD COLUMN image_path TEXT DEFAULT ''")

    # 위험성평가 테이블 신설
    c.execute("""
        CREATE TABLE IF NOT EXISTS risk_assessments (
            id           TEXT PRIMARY KEY,
            project_id   TEXT,
            eval_date    TEXT NOT NULL DEFAULT '',
            task_name    TEXT NOT NULL DEFAULT '',
            evaluator    TEXT NOT NULL DEFAULT '',
            content      TEXT NOT NULL DEFAULT '',
            file_name    TEXT NOT NULL DEFAULT '',
            file_path    TEXT NOT NULL DEFAULT '',
            creator_id   TEXT DEFAULT '',
            created_at   TEXT NOT NULL
        )
    """)

    conn.commit()





def init_db():
    """테이블 생성 및 시드 데이터 삽입"""
    conn = get_db()
    c = conn.cursor()

    # ── 테이블 생성 ──────────────────────────────────────────
    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id            TEXT PRIMARY KEY,
            email         TEXT NOT NULL UNIQUE,
            name          TEXT NOT NULL,
            role          TEXT NOT NULL DEFAULT 'employee',
            department    TEXT NOT NULL DEFAULT '',
            created_at    TEXT NOT NULL,
            password_hash TEXT NOT NULL DEFAULT '',
            status        TEXT NOT NULL DEFAULT 'active',
            team          TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS pending_users (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            department  TEXT NOT NULL DEFAULT '',
            team        TEXT NOT NULL DEFAULT '',
            status      TEXT NOT NULL DEFAULT 'pending',
            created_at  TEXT NOT NULL,
            reviewed_by TEXT DEFAULT '',
            reviewed_at TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS projects (
            id               TEXT PRIMARY KEY,
            project_name     TEXT NOT NULL,
            contract_amount  TEXT NOT NULL DEFAULT '0원',
            start_date       TEXT NOT NULL,
            end_date         TEXT NOT NULL,
            period_text      TEXT NOT NULL DEFAULT '',
            client_name      TEXT NOT NULL DEFAULT '',
            contractor_name  TEXT NOT NULL DEFAULT '',
            location         TEXT DEFAULT '',
            description      TEXT DEFAULT '',
            extra_notes      TEXT DEFAULT '',
            site_manager     TEXT DEFAULT '',
            safety_manager   TEXT DEFAULT '',
            updated_at       TEXT NOT NULL,
            updated_by       TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS user_site_assignments (
            id          TEXT PRIMARY KEY,
            user_id     TEXT NOT NULL,
            project_id  TEXT NOT NULL,
            assigned_by TEXT NOT NULL DEFAULT '',
            assigned_at TEXT NOT NULL,
            UNIQUE(user_id, project_id)
        );

        CREATE TABLE IF NOT EXISTS app_config (
            key   TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS workers (
            id          TEXT PRIMARY KEY,
            project_id  TEXT,
            name        TEXT NOT NULL,
            birth_date  TEXT NOT NULL,
            gender      TEXT NOT NULL DEFAULT '남',
            nationality TEXT NOT NULL DEFAULT '대한민국',
            contact     TEXT DEFAULT '',
            job_type    TEXT NOT NULL,
            site_name   TEXT DEFAULT '',
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS work_plans (
            id                       TEXT PRIMARY KEY,
            project_id               TEXT,
            site_name                TEXT NOT NULL,
            company_name             TEXT NOT NULL DEFAULT '',
            created_date             TEXT NOT NULL,
            plan_category            TEXT NOT NULL DEFAULT '차량계 건설기계',
            heavy_handling           INTEGER NOT NULL DEFAULT 0,
            machinery_name           TEXT NOT NULL DEFAULT '',
            equipment_plan_type      TEXT NOT NULL DEFAULT '',
            specification            TEXT DEFAULT '',
            vehicle_number           TEXT DEFAULT '',
            equipment_year           TEXT DEFAULT '',
            registered_vendor        TEXT DEFAULT '',
            insurance_expiry_date    TEXT DEFAULT '',
            inspection_validity_date TEXT DEFAULT '',
            ndt_testing_date         TEXT DEFAULT '',
            training_date            TEXT DEFAULT '',
            usage_start_date         TEXT DEFAULT '',
            usage_end_date           TEXT DEFAULT '',
            usage_location           TEXT DEFAULT '',
            creator_id               TEXT,
            creator_name             TEXT,
            created_at               TEXT NOT NULL,
            updated_at               TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS tbm_logs (
            id                    TEXT PRIMARY KEY,
            project_id            TEXT,
            project_name          TEXT NOT NULL,
            project_period        TEXT NOT NULL DEFAULT '',
            instructor            TEXT NOT NULL,
            work_details_hazards  TEXT NOT NULL,
            safety_measures       TEXT NOT NULL,
            special_notes         TEXT DEFAULT '',
            created_date          TEXT NOT NULL,
            creator_id            TEXT,
            creator_name          TEXT,
            created_at            TEXT NOT NULL,
            updated_at            TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS risk_assessments (
            id           TEXT PRIMARY KEY,
            project_id   TEXT,
            eval_date    TEXT NOT NULL DEFAULT '',
            task_name    TEXT NOT NULL DEFAULT '',
            evaluator    TEXT NOT NULL DEFAULT '',
            content      TEXT NOT NULL DEFAULT '',
            file_name    TEXT NOT NULL DEFAULT '',
            file_path    TEXT NOT NULL DEFAULT '',
            creator_id   TEXT DEFAULT '',
            created_at   TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS documents (
            id                  TEXT PRIMARY KEY,
            project_id          TEXT,
            project_name        TEXT DEFAULT '',
            title               TEXT NOT NULL,
            original_file_name  TEXT NOT NULL,
            file_type           TEXT NOT NULL DEFAULT 'other',
            mime_type           TEXT NOT NULL DEFAULT 'application/octet-stream',
            file_size           INTEGER NOT NULL DEFAULT 0,
            main_category       TEXT NOT NULL DEFAULT '공사정보',
            sub_category        TEXT NOT NULL DEFAULT '',
            category            TEXT NOT NULL DEFAULT '',
            tags                TEXT NOT NULL DEFAULT '[]',
            uploader_id         TEXT NOT NULL,
            uploader_name       TEXT NOT NULL,
            uploader_role       TEXT NOT NULL DEFAULT 'employee',
            uploader_department TEXT NOT NULL DEFAULT '',
            visibility          TEXT NOT NULL DEFAULT 'all',
            target_department   TEXT DEFAULT '',
            created_at          TEXT NOT NULL,
            updated_at          TEXT NOT NULL,
            file_path           TEXT DEFAULT '',
            download_count      INTEGER NOT NULL DEFAULT 0,
            view_count          INTEGER NOT NULL DEFAULT 1,
            ai_summary          TEXT DEFAULT '',
            ai_key_insights     TEXT DEFAULT '[]',
            ai_extracted_text   TEXT DEFAULT '',
            ai_detected_columns TEXT DEFAULT '[]',
            ai_auto_tags        TEXT DEFAULT '[]'
        );

        CREATE TABLE IF NOT EXISTS audit_logs (
            id              TEXT PRIMARY KEY,
            timestamp       TEXT NOT NULL,
            user_id         TEXT NOT NULL,
            user_name       TEXT NOT NULL,
            user_role       TEXT NOT NULL,
            action          TEXT NOT NULL,
            document_id     TEXT DEFAULT '',
            document_title  TEXT DEFAULT '',
            details         TEXT NOT NULL
        );
    """)

    # 마이그레이션 (기존 DB 컬럼 추가)
    _migrate(conn)

    # ── 시드 데이터 삽입 (이미 있으면 SKIP) ──────────────────
    existing = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if existing > 0:
        conn.close()
        return

    now = datetime.now().isoformat()
    admin_pw = generate_password_hash(ADMIN_PASSWORD)

    # 사용자
    users = [
        ('usr_admin_1', 'admin@ipark.com', '관리자', 'admin', '안전관리팀',
         '2025-01-10T09:00:00', admin_pw, 'active', '안전관리팀'),
        ('usr_staff_1', 'staff1@ipark.com', '이직원', 'employee', '영업팀',
         '2025-02-15T10:30:00', '', 'active', '영업1팀'),
        ('usr_staff_2', 'staff2@ipark.com', '박직원', 'employee', '기술팀',
         '2025-03-01T11:00:00', '', 'active', '기술지원팀'),
    ]
    c.executemany(
        "INSERT INTO users VALUES (?,?,?,?,?,?,?,?,?)", users
    )

    # 공사 프로젝트
    projects = [
        ('proj_1', '서울 스마트 메트로 3공구 건설공사', '48,500,000,000원',
         '2026-01-01', '2028-12-31', '2026.01.01 ~ 2028.12.31 (36개월)',
         '서울교통공사', '한국건설(주) 컨소시엄',
         '서울특별시 성동구 ~ 동대문구 연장구간 (4.2km)',
         'BIM 및 IoT 기반 스마트 안전 통제 시스템 적용 현장',
         '2026-05-01T10:00:00', '관리자'),
        ('proj_2', 'IPARK 리조트 3단계 콘도미니엄 신축공사', '35,000,000,000원',
         '2026-03-01', '2027-11-30', '2026.03.01 ~ 2027.11.30 (21개월)',
         'HDC IPARK RESORT', 'HDC현대산업개발(주)',
         '강원도 속초시 설악산로 109',
         '초고층 콘도 타워 2개동 및 부대 시설 신축 작업',
         '2026-05-02T11:00:00', '관리자'),
    ]
    c.executemany(
        "INSERT INTO projects VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", projects
    )

    c.execute("INSERT OR REPLACE INTO app_config VALUES ('active_project_id', 'proj_2')")

    # 근로자
    workers = [
        ('wrk_1', 'proj_1', '홍길동', '1982-05-14', '남', '대한민국', '010-3829-1928', '작업반장',
         '서울 스마트 메트로 3공구 건설공사', '2026-01-15T09:00:00', '2026-01-15T09:00:00'),
        ('wrk_2', 'proj_1', '김철수', '1978-11-03', '남', '대한민국', '010-8821-4910', '장비운전원',
         '서울 스마트 메트로 3공구 건설공사', '2026-01-20T10:00:00', '2026-01-20T10:00:00'),
        ('wrk_3', 'proj_1', '이영희', '1990-03-22', '여', '대한민국', '010-5512-9018', '신호수',
         '서울 스마트 메트로 3공구 건설공사', '2026-02-01T11:00:00', '2026-02-01T11:00:00'),
        ('wrk_5', 'proj_2', '최리조트', '1980-07-19', '남', '대한민국', '010-7711-2233', '작업반장',
         'IPARK리조트 3단계 신축 공사', '2026-03-01T08:00:00', '2026-03-01T08:00:00'),
    ]
    c.executemany(
        "INSERT INTO workers VALUES (?,?,?,?,?,?,?,?,?,?,?)", workers
    )

    # 작업계획서
    work_plans = [
        ('wp_1', 'proj_1', '서울 스마트 메트로 3공구 건설공사', '한국건설(주)', '2026-02-01',
         '차량계 건설기계', 1, '굴착기 (0.8m³)', '굴착기', '0.8m³ (20ton급)',
         '서울02가1234', '2022년식', '(주)중기중앙',
         '2026-12-31', '2026-11-15', '2026-01-10', '2026-02-01',
         '2026-02-01', '2026-05-31', '3공구 A구간 터파기 현장',
         'usr_admin_1', '관리자', '2026-02-01T08:00:00', '2026-02-01T08:00:00'),
        ('wp_3', 'proj_2', 'IPARK리조트 3단계 콘도미니엄 신축공사', 'HDC현대산업개발(주)', '2026-03-01',
         '차량계 건설기계', 0, '덤프트럭 (25톤)', '덤프트럭', '25톤 상용',
         '강원99다1122', '2024년식', '(주)강원토건',
         '2027-01-15', '2026-12-20', '2026-02-10', '2026-03-01',
         '2026-03-01', '2026-08-31', 'IPARK리조트 A동 토공사 및 잔토처리장',
         'usr_admin_1', '관리자', '2026-03-01T09:00:00', '2026-03-01T09:00:00'),
    ]
    c.executemany(
        """INSERT INTO work_plans VALUES
           (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        work_plans
    )

    # TBM 일지
    tbm_logs = [
        ('tbm_1', 'proj_2', 'IPARK리조트 A동 리모델링 및 안전개선공사',
         '2026.03.01 ~ 2026.11.30', '김철수 안전관리자',
         'A동 3층 외벽 비가공 타일 철거 및 자재 인양 작업. 낙하물 위험 및 고소 작업 시 추락 위험 존재.',
         '안전대 체결 상태 전원 재점검, 낙하물 방지망 설치 확인, 하부 신호수 배치 및 통제 구역 설정.',
         '작업 전 신규 투입 인원 2명 신규자 안전교육 완료 상태 확인 및 개인보호구 밀착착용 지도.',
         now[:10], 'usr_admin_1', '관리자', now, now),
    ]
    c.executemany(
        "INSERT INTO tbm_logs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", tbm_logs
    )

    # 문서 (샘플)
    documents = [
        ('doc_101', 'proj_2', 'IPARK 리조트 3단계 콘도미니엄 신축공사',
         'IPARK 리조트 3단계 공사 기본 개요서.pdf',
         'IPARK_Resort_Construction_Overview.pdf', 'pdf', 'application/pdf', 1250000,
         '공사정보', '공사명', '공사명',
         json.dumps(['공사명', 'IPARK', '리조트', '개요서', '공사정보'], ensure_ascii=False),
         'usr_admin_1', '관리자', 'admin', '안전관리팀', 'all', '',
         '2026-04-02T14:20:00', '2026-04-02T14:20:00', '', 42, 128,
         'IPARK 리조트 3단계 콘도미니엄 신축 공사 기본 개요서입니다.',
         json.dumps(['총 공사비 350억원 규모', '콘도 타워 2개동 신축'], ensure_ascii=False),
         '공사명: IPARK 리조트 3단계 콘도미니엄 신축공사',
         json.dumps([], ensure_ascii=False)),
        ('doc_108', None, '',
         '착공 전 최초 위험성평가표 및 위험요인 감소대책.pdf',
         'Initial_Risk_Assessment_Report.pdf', 'pdf', 'application/pdf', 3100000,
         '위험성평가', '최초 위험성평가', '최초 위험성평가',
         json.dumps(['최초위험성평가', '위험요인', '감소대책', '착공전평가'], ensure_ascii=False),
         'usr_admin_1', '관리자', 'admin', '안전관리팀', 'all', '',
         '2026-01-15T11:00:00', '2026-01-15T11:00:00', '', 48, 142,
         '공사 착공 전 현장 전체 공종에 대한 최초 위험성평가 매트릭스 문서입니다.',
         json.dumps(['위험성 감소 대책 조치 후 재평가 지수 도출'], ensure_ascii=False),
         '최초 위험성평가 결과: 상(High) 8건, 중(Medium) 22건, 하(Low) 15건.',
         json.dumps([], ensure_ascii=False)),
    ]
    c.executemany(
        """INSERT INTO documents
           (id, project_id, project_name, title, original_file_name,
            file_type, mime_type, file_size, main_category, sub_category,
            category, tags, uploader_id, uploader_name, uploader_role,
            uploader_department, visibility, target_department,
            created_at, updated_at, file_path, download_count, view_count,
            ai_summary, ai_key_insights, ai_extracted_text, ai_detected_columns)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        documents
    )

    # 감사 로그
    audit_logs = [
        ('log_001', '2026-04-02T14:20:00', 'usr_admin_1', '관리자', 'admin',
         'UPLOAD', 'doc_101', 'IPARK 리조트 3단계 공사 기본 개요서.pdf',
         '공사정보 카테고리에 PDF 문서를 업로드했습니다.'),
    ]
    c.executemany(
        "INSERT INTO audit_logs VALUES (?,?,?,?,?,?,?,?,?)", audit_logs
    )

    conn.commit()
    conn.close()
    print("Database init complete (seed data inserted)")


if __name__ == '__main__':
    init_db()
    print(f"DB 위치: {DB_PATH}")
