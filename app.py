"""
Smart DMS — Flask 메인 애플리케이션
일용직 근로자 정보 및 공사 정보 관리 로컬 웹 서버
"""
import os
import json
import uuid
import mimetypes
from datetime import datetime
from functools import wraps
from flask import (
    Flask, jsonify, request, send_from_directory,
    render_template, session, abort, make_response
)
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash
import sqlite3 as _sqlite3
from database import get_db, init_db, DB_PATH

# ── 앱 설정 ─────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.secret_key = 'smart-dms-secret-key-2026'
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

ALLOWED_EXTENSIONS = {
    'xlsx', 'xls', 'csv', 'pdf', 'doc', 'docx', 'hwp', 'zip',
    'png', 'jpg', 'jpeg', 'webp', 'gif', 'txt'
}

CATEGORY_MAP = {
    '공사정보': ['공사명', '공사금액', '공사기간'],
    '작업관리': ['작업계획서', '근로자 이력정보', '출역 현황'],
    '교육': ['TBM', '근로자 정기교육', '관리감독자 교육'],
    '위험성평가': ['최초 위험성평가', '정기 위험성평가', '수시 위험성평가'],
}


# ── 유틸리티 ─────────────────────────────────────────────────
def new_id(prefix='id'):
    return f"{prefix}_{int(datetime.now().timestamp()*1000)}_{uuid.uuid4().hex[:4]}"


def now_iso():
    return datetime.now().isoformat()


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def detect_file_type(filename, mime=''):
    name = (filename or '').lower()
    mime = (mime or '').lower()
    if any(name.endswith(e) for e in ['.xlsx', '.xls', '.csv']) or 'spreadsheet' in mime or 'excel' in mime:
        return 'excel'
    if any(name.endswith(e) for e in ['.png', '.jpg', '.jpeg', '.webp', '.gif']) or 'image' in mime:
        return 'image'
    if name.endswith('.pdf') or 'pdf' in mime:
        return 'pdf'
    if any(name.endswith(e) for e in ['.docx', '.doc', '.txt']) or 'word' in mime or 'text' in mime:
        return 'doc'
    return 'other'


def add_audit_log(user_id, user_name, user_role, action, details,
                  doc_id='', doc_title=''):
    db = get_db()
    try:
        db.execute(
            "INSERT INTO audit_logs VALUES (?,?,?,?,?,?,?,?,?)",
            (new_id('log'), now_iso(), user_id, user_name,
             user_role, action, doc_id, doc_title, details)
        )
        db.commit()
    finally:
        db.close()


def get_active_project_id():
    db = get_db()
    try:
        row = db.execute(
            "SELECT value FROM app_config WHERE key='active_project_id'"
        ).fetchone()
        return row['value'] if row else None
    finally:
        db.close()


def set_active_project_id(pid):
    db = get_db()
    try:
        db.execute(
            "INSERT OR REPLACE INTO app_config VALUES ('active_project_id', ?)", (pid,)
        )
        db.commit()
    finally:
        db.close()


def row_to_dict(row):
    if row is None:
        return None
    return dict(row)


def rows_to_list(rows):
    return [dict(r) for r in rows]


def parse_json_field(value, default=None):
    if default is None:
        default = []
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def doc_row_to_dict(row):
    d = dict(row)
    d['tags'] = parse_json_field(d.get('tags'), [])
    d['ai_key_insights'] = parse_json_field(d.get('ai_key_insights'), [])
    d['ai_detected_columns'] = parse_json_field(d.get('ai_detected_columns'), [])
    # Nest AI metadata
    d['aiMetadata'] = {
        'summary': d.pop('ai_summary', ''),
        'keyInsights': d.pop('ai_key_insights', []),
        'extractedText': d.pop('ai_extracted_text', ''),
        'detectedColumns': d.pop('ai_detected_columns', []),
    }
    return d


def can_access_doc(doc, user):
    """권한 체크: 관리자는 모두 접근 가능"""
    if user['role'] == 'admin':
        return True
    vis = doc.get('visibility', 'all')
    if vis == 'admin_only':
        return False
    if vis == 'department':
        return (doc.get('target_department') == user.get('department') or
                doc.get('uploader_department') == user.get('department'))
    return True


def get_current_user_id():
    return session.get('user_id')

def get_user(user_id=None):
    db = get_db()
    try:
        if not user_id:
            user_id = get_current_user_id()
        if user_id:
            row = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            if row:
                return row_to_dict(row)
        return None
    finally:
        db.close()


def get_user_assigned_project_ids(user_id: str) -> list:
    """직원의 배정 현장 ID 목록 반환. 관리자이면 None 반환 (전체 허용)"""
    db = get_db()
    try:
        user = row_to_dict(db.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone())
        if not user:
            return []
        if user['role'] == 'admin':
            return None  # 전체 허용
        rows = db.execute(
            "SELECT project_id FROM user_site_assignments WHERE user_id=?", (user_id,)
        ).fetchall()
        return [r['project_id'] for r in rows]
    finally:
        db.close()

# ── 메인 페이지 ──────────────────────────────────────────────
@app.route('/')
def index():
    resp = make_response(render_template('index.html'))
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp


# ── DB 마이그레이션 (서버 시작 시 1회 실행) ──────────────────
def _run_migrations():
    """누락된 컬럼을 자동으로 추가하는 마이그레이션"""
    conn = _sqlite3.connect(DB_PATH)
    conn.row_factory = _sqlite3.Row
    try:
        # workers 테이블: creator_id
        w_cols = {row[1] for row in conn.execute("PRAGMA table_info(workers)").fetchall()}
        if 'creator_id' not in w_cols:
            conn.execute("ALTER TABLE workers ADD COLUMN creator_id TEXT DEFAULT ''")
        # tbm_logs 테이블: image_path
        t_cols = {row[1] for row in conn.execute("PRAGMA table_info(tbm_logs)").fetchall()}
        if 'image_path' not in t_cols:
            conn.execute("ALTER TABLE tbm_logs ADD COLUMN image_path TEXT DEFAULT ''")
        # workplans 테이블: image_path
        wp_cols = {row[1] for row in conn.execute("PRAGMA table_info(workplans)").fetchall()}
        if 'image_path' not in wp_cols:
            conn.execute("ALTER TABLE workplans ADD COLUMN image_path TEXT DEFAULT ''")
        conn.commit()
    finally:
        conn.close()

_run_migrations()


# ── 업로드 파일 서빙 ─────────────────────────────────────────
def _get_original_filename(filename):
    db = get_db()
    try:
        # 1. documents
        row = db.execute("SELECT original_file_name FROM documents WHERE file_path=?", (filename,)).fetchone()
        if row and row['original_file_name']: 
            return row['original_file_name']
        
        # 2. risk_assessments
        row = db.execute("SELECT file_name FROM risk_assessments WHERE file_path=?", (filename,)).fetchone()
        if row and row['file_name']: 
            return row['file_name']
    except Exception:
        pass
        
    # 3. 그 외 (작업계획서 등) 확장자 복구 로직 (기존 정규식 개선)
    import re
    m = re.search(r'_(png|jpg|jpeg|gif|webp|pdf|xlsx|xls|doc|docx|ppt|pptx|csv|txt|zip|hwp)$', filename, re.I)
    if m:
        ext = m.group(1)
        return filename[:m.start()] + '.' + ext
    return filename

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    download_name = _get_original_filename(filename)
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, download_name=download_name)

@app.route('/uploads/<path:filename>/download')
def download_uploaded_file(filename):
    """파일을 브라우저에서 직접 다운로드 - 확장자 없는 기존 파일도 정상 다운로드"""
    download_name = _get_original_filename(filename)
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True, download_name=download_name)


# ── 정적 파일 서빙 (로고 등) ────────────────────────────────
STATIC_FOLDER = os.path.join(BASE_DIR, 'static')
@app.route('/static/<path:filename>')
def static_file(filename):
    return send_from_directory(STATIC_FOLDER, filename)


# ════════════════════════════════════════════════════════════
# 1. 인증 & 사용자 관리 API
# ════════════════════════════════════════════════════════════

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'success': True})

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.get_json()
    login_type = data.get('type', 'admin')   # 'admin' | 'employee'
    db = get_db()
    try:
        if login_type == 'admin':
            # 관리자: ID(email 필드에 저장) + 비밀번호 검증
            login_id = data.get('login_id', '').strip()
            password = data.get('password', '')
            if not login_id or not password:
                return jsonify({'error': 'ID와 비밀번호를 입력해주세요.'}), 400
            user = row_to_dict(db.execute(
                "SELECT * FROM users WHERE email=? AND role='admin'", (login_id,)
            ).fetchone())
            if not user:
                return jsonify({'error': '관리자 계정을 찾을 수 없습니다.'}), 404
            if not check_password_hash(user.get('password_hash', ''), password):
                return jsonify({'error': '비밀번호가 올바르지 않습니다.'}), 401
        else:
            # 직원: 이름 + 비밀번호 로그인
            name       = data.get('name', '').strip()
            password   = data.get('password', '')
            department = data.get('department', '').strip()
            if not name:
                return jsonify({'error': '이름을 입력해주세요.'}), 400
            if not password:
                return jsonify({'error': '비밀번호를 입력해주세요.'}), 400
            sql = "SELECT * FROM users WHERE name=? AND role='employee' AND status='active'"
            params = [name]
            if department:
                sql += " AND (department=? OR team=?)"
                params += [department, department]
            user = row_to_dict(db.execute(sql, params).fetchone())
            if not user:
                return jsonify({'error': '등록된 직원 계정을 찾을 수 없습니다.\n계정 신청 후 관리자 승인을 받아주세요.'}), 404
            if not check_password_hash(user.get('password_hash', ''), password):
                return jsonify({'error': '비밀번호가 올바르지 않습니다.\n초기 비밀번호: 0000'}), 401
        if user:
            add_audit_log(user['id'], user['name'], user['role'], 'LOGIN',
                          f"{user['name']}({user['role']}) 로그인 성공")
            # 배정된 현장 목록 반환 (직원용)
            assigned_projects = []
            if user['role'] == 'employee':
                assigned_rows = db.execute(
                    """SELECT p.id, p.project_name, p.start_date, p.end_date,
                              p.site_manager, p.safety_manager, p.client_name
                       FROM user_site_assignments usa
                       JOIN projects p ON p.id = usa.project_id
                       WHERE usa.user_id = ?
                       ORDER BY usa.assigned_at DESC""",
                    (user['id'],)
                ).fetchall()
                assigned_projects = rows_to_list(assigned_rows)
            elif user['role'] == 'admin':
                # 관리자: 전체 현장 목록
                all_proj_rows = db.execute(
                    "SELECT id, project_name, start_date, end_date, site_manager, client_name FROM projects ORDER BY updated_at DESC"
                ).fetchall()
                assigned_projects = rows_to_list(all_proj_rows)
            session['user_id'] = user['id']
            session['role'] = user['role']
            return jsonify({'success': True, 'user': user, 'assignedProjects': assigned_projects})
        return jsonify({'error': '사용자를 찾을 수 없습니다.'}), 404
    finally:
        db.close()



@app.route('/api/auth/register', methods=['POST'])
def register_request():
    """직원 계정 신청 (관리자 승인 필요)"""
    data = request.get_json()
    name       = (data.get('name') or '').strip()
    department = (data.get('department') or '').strip()
    team       = (data.get('team') or '').strip()
    password   = (data.get('password') or '0000').strip()
    if not name or not department:
        return jsonify({'error': '이름과 부서는 필수 항목입니다.'}), 400
    if not password:
        password = '0000'
    db = get_db()
    try:
        # 중복 신청 방지
        dup = db.execute(
            "SELECT id FROM pending_users WHERE name=? AND status='pending'", (name,)
        ).fetchone()
        if dup:
            return jsonify({'error': '이미 승인 대기 중인 신청이 있습니다.'}), 409
        # 이미 활성 계정 있는지 확인
        exist = db.execute(
            "SELECT id FROM users WHERE name=? AND status='active'", (name,)
        ).fetchone()
        if exist:
            return jsonify({'error': '이미 등록된 계정이 있습니다.'}), 409
        pid = new_id('pend')
        from werkzeug.security import generate_password_hash as _gph
        pw_hash = _gph(password)
        db.execute(
            """INSERT INTO pending_users
               (id, name, department, team, password_hash, status, created_at, reviewed_by, reviewed_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (pid, name, department, team, pw_hash, 'pending', now_iso(), '', '')
        )
        db.commit()
        return jsonify({'success': True, 'message': '계정 신청이 완료되었습니다. 관리자 승인 후 로그인 가능합니다.'})
    finally:
        db.close()



@app.route('/api/auth/deleted-employees', methods=['GET'])
def get_deleted_employees():
    user_id = get_current_user_id()
    admin = get_user(user_id)
    if not admin or admin.get('role') != 'admin':
        return jsonify({'error': '권한이 없습니다.'}), 403
    db = get_db()
    try:
        employees = rows_to_list(db.execute(
            "SELECT id, name, department, team, status, created_at FROM users WHERE role='employee' AND status IN ('deleted', 'suspended') ORDER BY created_at DESC"
        ).fetchall())
        return jsonify({'success': True, 'employees': employees})
    finally:
        db.close()

@app.route('/api/auth/hard-delete-accounts', methods=['POST'])
def hard_delete_accounts():
    data = request.get_json() or {}
    user_id = get_current_user_id()
    account_ids = data.get('accountIds', [])
    admin = get_user(user_id)
    if not admin or admin['role'] != 'admin':
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403
    if not account_ids:
        return jsonify({'error': '삭제할 계정이 없습니다.'}), 400
        
    db = get_db()
    try:
        placeholders = ','.join('?' * len(account_ids))
        # Ensure we only delete accounts that are already in 'deleted' status to be safe
        db.execute(f"DELETE FROM users WHERE id IN ({placeholders}) AND status='deleted'", account_ids)
        db.commit()
        
        add_audit_log(admin['id'], admin['name'], admin['role'], 'DELETE',
                      f"계정 {len(account_ids)}건 영구 삭제", 'bulk', '')
        return jsonify({'success': True})
    finally:
        db.close()

@app.route('/api/auth/delete-accounts', methods=['POST'])
def delete_accounts():
    data = request.get_json() or {}
    user_id = get_current_user_id()
    account_ids = data.get('accountIds', [])
    admin = get_user(user_id)
    if not admin or admin.get('role') != 'admin':
        return jsonify({'error': '권한이 없습니다.'}), 403
    
    if not account_ids:
        return jsonify({'error': '선택된 계정이 없습니다.'}), 400
        
    db = get_db()
    try:
        placeholders = ','.join('?' * len(account_ids))
        query = f"UPDATE users SET status='deleted' WHERE id IN ({placeholders})"
        db.execute(query, account_ids)
        db.commit()
        return jsonify({'success': True})
    finally:
        db.close()

@app.route('/api/auth/restore-accounts', methods=['POST'])
def restore_accounts():
    data = request.get_json() or {}
    user_id = get_current_user_id()
    account_ids = data.get('accountIds', [])
    admin = get_user(user_id)
    if not admin or admin.get('role') != 'admin':
        return jsonify({'error': '권한이 없습니다.'}), 403
    
    if not account_ids:
        return jsonify({'error': '선택된 계정이 없습니다.'}), 400
        
    db = get_db()
    try:
        placeholders = ','.join('?' * len(account_ids))
        query = f"UPDATE users SET status='active' WHERE id IN ({placeholders})"
        db.execute(query, account_ids)
        db.commit()
        return jsonify({'success': True})
    finally:
        db.close()

@app.route('/api/auth/pending', methods=['GET'])
def get_pending_users():
    """관리자용: 대기 중인 계정 신청 목록"""
    user_id = get_current_user_id()
    admin = get_user(user_id)
    if not admin or admin.get('role') != 'admin':
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403
    db = get_db()
    try:
        pending = rows_to_list(db.execute(
            "SELECT * FROM pending_users ORDER BY created_at DESC"
        ).fetchall())
        return jsonify({'success': True, 'pending': pending})
    finally:
        db.close()


@app.route('/api/auth/approve/<pid>', methods=['POST'])
def approve_user(pid):
    """관리자: 계정 신청 승인"""
    data = request.get_json() or {}
    admin = get_user(get_current_user_id())
    if not admin or admin.get('role') != 'admin':
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403
    db = get_db()
    try:
        pend = row_to_dict(db.execute("SELECT * FROM pending_users WHERE id=?", (pid,)).fetchone())
        if not pend:
            return jsonify({'error': '신청 정보를 찾을 수 없습니다.'}), 404
        # users 테이블에 추가
        uid = new_id('usr')
        email = f"{uid}@ipark-staff.local"
        pw_hash = pend.get('password_hash') or ''
        if not pw_hash:
            from werkzeug.security import generate_password_hash as _gph
            pw_hash = _gph('0000')
        db.execute(
            "INSERT INTO users VALUES (?,?,?,?,?,?,?,?,?)",
            (uid, email, pend['name'], 'employee',
             pend['department'], now_iso(), pw_hash, 'active', pend['team'])
        )
        db.execute(
            "UPDATE pending_users SET status='approved', reviewed_by=?, reviewed_at=? WHERE id=?",
            (admin['name'], now_iso(), pid)
        )
        db.commit()
        add_audit_log(admin['id'], admin['name'], admin['role'], 'USER_ROLE_CHANGE',
                      f"직원 계정 승인: [{pend['name']} / {pend['department']} {pend['team']}]")
        return jsonify({'success': True, 'message': f"{pend['name']} 계정이 승인되었습니다."})
    finally:
        db.close()


@app.route('/api/auth/reject/<pid>', methods=['POST'])
def reject_user(pid):
    """관리자: 계정 신청 거절"""
    data = request.get_json() or {}
    admin = get_user(get_current_user_id())
    if not admin or admin.get('role') != 'admin':
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403
    db = get_db()
    try:
        pend = row_to_dict(db.execute("SELECT * FROM pending_users WHERE id=?", (pid,)).fetchone())
        if not pend:
            return jsonify({'error': '신청 정보를 찾을 수 없습니다.'}), 404
        db.execute(
            "UPDATE pending_users SET status='rejected', reviewed_by=?, reviewed_at=? WHERE id=?",
            (admin['name'], now_iso(), pid)
        )
        db.commit()
        return jsonify({'success': True, 'message': f"{pend['name']} 계정 신청이 거절되었습니다."})
    finally:
        db.close()

@app.route('/api/auth/suspend-pending/<pid>', methods=['POST'])
def suspend_pending_user(pid):
    """관리자: 신청 계정 승인 후 즉시 미사용(정지) 처리"""
    from werkzeug.security import generate_password_hash as _gph
    data = request.get_json() or {}
    admin = get_user(get_current_user_id())
    if not admin or admin.get('role') != 'admin':
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403
    db = get_db()
    try:
        pend = row_to_dict(db.execute("SELECT * FROM pending_users WHERE id=?", (pid,)).fetchone())
        if not pend:
            return jsonify({'error': '신청 정보를 찾을 수 없습니다.'}), 404
        uid = new_id('usr')
        email = f"{uid}@ipark-staff.local"
        pw_hash = pend.get('password_hash') or _gph('0000')
        db.execute(
            "INSERT INTO users VALUES (?,?,?,?,?,?,?,?,?)",
            (uid, email, pend['name'], 'employee',
             pend['department'], now_iso(), pw_hash, 'suspended', pend['team'])
        )
        db.execute(
            "UPDATE pending_users SET status='approved', reviewed_by=?, reviewed_at=? WHERE id=?",
            (admin['name'], now_iso(), pid)
        )
        db.commit()
        add_audit_log(admin['id'], admin['name'], admin['role'], 'USER_ROLE_CHANGE',
                      f"계정 미사용 처리: [{pend['name']} / {pend['department']}]")
        return jsonify({'success': True, 'message': f"{pend['name']} 계정이 미사용 상태로 처리되었습니다."})
    finally:
        db.close()


@app.route('/api/auth/toggle-status/<uid>', methods=['POST'])
def toggle_user_status(uid):
    """관리자: 직원 계정 활성/미사용 토글"""
    data = request.get_json() or {}
    admin = get_user(get_current_user_id())
    if not admin or admin.get('role') != 'admin':
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403
    db = get_db()
    try:
        target = row_to_dict(db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())
        if not target:
            return jsonify({'error': '사용자를 찾을 수 없습니다.'}), 404
        new_status = 'deleted'
        db.execute("UPDATE users SET status=? WHERE id=?", (new_status, uid))
        db.commit()
        label = '미사용'
        add_audit_log(admin['id'], admin['name'], admin['role'], 'USER_ROLE_CHANGE',
                      f"계정 상태 변경: [{target['name']}] → {new_status}")
        return jsonify({'success': True,
                        'newStatus': new_status,
                        'message': f"{target['name']} 계정이 {label} 처리(휴지통 이동) 되었습니다."})
    finally:
        db.close()







@app.route('/api/auth/reset-password/<uid>', methods=['POST'])
def reset_password(uid):
    """관리자: 직원 비밀번호 초기화 (→ 0000)"""
    from werkzeug.security import generate_password_hash as _gph
    data = request.get_json() or {}
    admin = get_user(get_current_user_id())
    if not admin or admin.get('role') != 'admin':
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403
    db = get_db()
    try:
        target = row_to_dict(db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())
        if not target:
            return jsonify({'error': '사용자를 찾을 수 없습니다.'}), 404
        db.execute("UPDATE users SET password_hash=? WHERE id=?", (_gph('0000'), uid))
        db.commit()
        add_audit_log(admin['id'], admin['name'], admin['role'], 'USER_ROLE_CHANGE',
                      f"비밀번호 초기화: [{target['name']}] → 0000")
        return jsonify({'success': True, 'message': f"{target['name']} 비밀번호가 0000으로 초기화되었습니다."})
    finally:
        db.close()



@app.route('/api/auth/employees', methods=['GET'])
def get_employees():
    """관리자용: 전체 직원 계정 목록 (배정 현장 포함)"""
    user_id = get_current_user_id()
    admin = get_user(user_id)
    if not admin or admin.get('role') != 'admin':
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403
    db = get_db()
    try:
        employees = rows_to_list(db.execute(
            "SELECT id, name, department, team, status, created_at FROM users WHERE role='employee' AND status='active' ORDER BY created_at DESC"
        ).fetchall())
        # 각 직원의 배정 현장 목록 추가
        for emp in employees:
            rows = db.execute(
                """SELECT p.id, p.project_name FROM user_site_assignments usa
                   JOIN projects p ON p.id=usa.project_id WHERE usa.user_id=?
                   ORDER BY usa.assigned_at""",
                (emp['id'],)
            ).fetchall()
            emp['assigned_projects'] = [{'id': r['id'], 'project_name': r['project_name']} for r in rows]
        return jsonify({'success': True, 'employees': employees})
    finally:
        db.close()


@app.route('/api/auth/employees/<uid>/sites', methods=['GET'])
def get_user_sites(uid):
    """직원의 배정 현장 목록 조회"""
    admin_id = get_current_user_id()
    admin = get_user(admin_id)
    if not admin or admin.get('role') != 'admin':
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403
    db = get_db()
    try:
        rows = db.execute(
            """SELECT p.id, p.project_name, usa.assigned_at, usa.assigned_by
               FROM user_site_assignments usa
               JOIN projects p ON p.id=usa.project_id
               WHERE usa.user_id=? ORDER BY usa.assigned_at""",
            (uid,)
        ).fetchall()
        return jsonify({'success': True, 'sites': rows_to_list(rows)})
    finally:
        db.close()


@app.route('/api/auth/employees/<uid>/assign', methods=['POST'])
def assign_site(uid):
    """관리자: 직원에게 현장 배정"""
    data = request.get_json() or {}
    admin = get_user(get_current_user_id())
    if not admin or admin.get('role') != 'admin':
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403
    project_id = data.get('projectId', '').strip()
    if not project_id:
        return jsonify({'error': '현장 ID가 필요합니다.'}), 400
    db = get_db()
    try:
        target = row_to_dict(db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())
        if not target:
            return jsonify({'error': '사용자를 찾을 수 없습니다.'}), 404
        proj = row_to_dict(db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone())
        if not proj:
            return jsonify({'error': '현장을 찾을 수 없습니다.'}), 404
        assign_id = new_id('asa')
        try:
            db.execute(
                "INSERT INTO user_site_assignments VALUES (?,?,?,?,?)",
                (assign_id, uid, project_id, admin['name'], now_iso())
            )
            db.commit()
        except Exception:
            return jsonify({'error': '이미 배정된 현장입니다.'}), 409
        add_audit_log(admin['id'], admin['name'], admin['role'], 'USER_ROLE_CHANGE',
                      f"현장 배정: [{target['name']}] → [{proj['project_name']}]")
        return jsonify({'success': True, 'message': f"{target['name']}에게 [{proj['project_name']}] 현장이 배정되었습니다."})
    finally:
        db.close()


@app.route('/api/auth/employees/<uid>/assign/<project_id>', methods=['DELETE'])
def unassign_site(uid, project_id):
    """관리자: 직원 현장 배정 해제"""
    admin_id = get_current_user_id()
    admin = get_user(admin_id)
    if not admin or admin.get('role') != 'admin':
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403
    db = get_db()
    try:
        target = row_to_dict(db.execute("SELECT name FROM users WHERE id=?", (uid,)).fetchone())
        proj = row_to_dict(db.execute("SELECT project_name FROM projects WHERE id=?", (project_id,)).fetchone())
        db.execute("DELETE FROM user_site_assignments WHERE user_id=? AND project_id=?", (uid, project_id))
        db.commit()
        name = target['name'] if target else uid
        pname = proj['project_name'] if proj else project_id
        add_audit_log(admin['id'], admin['name'], admin['role'], 'USER_ROLE_CHANGE',
                      f"현장 배정 해제: [{name}] ← [{pname}]")
        return jsonify({'success': True, 'message': f"[{pname}] 현장 배정이 해제되었습니다."})
    finally:
        db.close()



@app.route('/api/users', methods=['GET'])
def get_users():
    db = get_db()
    try:
        users = rows_to_list(db.execute("SELECT * FROM users ORDER BY created_at").fetchall())
        return jsonify({'success': True, 'users': users})
    finally:
        db.close()


@app.route('/api/users/role', methods=['POST'])
def change_user_role():
    data = request.get_json()
    user_id = get_current_user_id()
    new_role = data.get('newRole')
    admin_id = get_current_user_id()
    db = get_db()
    try:
        admin = row_to_dict(db.execute("SELECT * FROM users WHERE id=?", (admin_id,)).fetchone())
        if not admin or admin['role'] != 'admin':
            return jsonify({'error': '관리자 권한이 필요합니다.'}), 403
        target = row_to_dict(db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())
        if not target:
            return jsonify({'error': '사용자를 찾을 수 없습니다.'}), 404
        old_role = target['role']
        db.execute("UPDATE users SET role=? WHERE id=?", (new_role, user_id))
        db.commit()
        target['role'] = new_role
        add_audit_log(admin['id'], admin['name'], admin['role'], 'USER_ROLE_CHANGE',
                      f"사용자 [{target['name']}] 권한 변경: {old_role} → {new_role}")
        return jsonify({'success': True, 'user': target})
    finally:
        db.close()


# ════════════════════════════════════════════════════════════
# 2. 공사정보 관리 API
# ════════════════════════════════════════════════════════════
def project_row(row):
    return dict(row) if row else None


@app.route('/api/project-info', methods=['GET'])
def get_project_info():
    user_id = get_current_user_id()
    view_as = request.args.get('viewAsUserId', '').strip()
    user = get_user(user_id) if user_id else None
    if user and user.get('role') == 'admin' and view_as:
        user = get_user(view_as)
    db = get_db()
    try:
        active_id = request.form.get('projectId') or get_active_project_id() or ''
        projects = rows_to_list(db.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall())
        if user and user.get('role') != 'admin':
            # [권한 격리] 직원은 본인에게 배정되었거나 직접 생성한(배정된) 공사만 조회 가능
            assigned = get_user_assigned_project_ids(user['id'])
            if assigned is not None:
                projects = [p for p in projects if p['id'] in assigned and p.get('status', 'active') != 'completed']
        
        proj_info = next((p for p in projects if p['id'] == active_id), None)
        if not proj_info and projects:
            proj_info = projects[0]
        return jsonify({'success': True, 'projectInfo': proj_info, 'projects': projects})
    finally:
        db.close()


@app.route('/api/project-info', methods=['POST'])
def create_project():
    data = request.get_json()
    user = get_user(get_current_user_id())
    project_name = data.get('projectName', '').strip()
    if not project_name:
        return jsonify({'error': '공사명을 입력해주세요.'}), 400
    pid = new_id('proj')
    start = data.get('startDate', '2026-01-01')
    end = data.get('endDate', '2028-12-31')
    period_text = data.get('periodText', f'{start} ~ {end}')
    n = now_iso()
    db = get_db()
    try:
        db.execute(
            """INSERT INTO projects VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (pid, project_name,
             data.get('contractAmount', '0원'), start, end, period_text,
             data.get('clientName', ''), data.get('contractorName', ''),
             data.get('location', ''), data.get('description', ''),
             n, user['name'] if user else '')
        )

        db.commit()
        set_active_project_id(pid)
        
        # [자동 권한 배정] 직원이 공사를 생성한 경우, 해당 직원에게 생성된 공사 권한을 즉시 부여
        if user and user.get('role') != 'admin':
            usa_id = new_id('usa')
            db.execute(
                "INSERT INTO user_site_assignments (id, user_id, project_id, assigned_by, assigned_at) VALUES (?, ?, ?, ?, ?)",
                (usa_id, user['id'], pid, user['name'], n)
            )
            db.commit()

        projects = rows_to_list(db.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall())
        proj_info = next((p for p in projects if p['id'] == pid), None)
        add_audit_log(user['id'] if user else '', user['name'] if user else '',
                      user['role'] if user else '', 'UPLOAD',
                      f"신규 공사 수기 작성/등록: [공사명: {project_name}]")
        return jsonify({'success': True, 'projectInfo': proj_info, 'projects': projects})
    finally:
        db.close()


@app.route('/api/project-info', methods=['PUT'])
def update_project():
    data = request.get_json()
    user = get_user(get_current_user_id())
    target_id = data.get('id') or get_active_project_id()
    if not target_id:
        return jsonify({'error': '공사 ID가 없습니다.'}), 400
    db = get_db()
    try:
        existing = row_to_dict(db.execute("SELECT * FROM projects WHERE id=?", (target_id,)).fetchone())
        if not existing:
            return jsonify({'error': '해당 공사를 찾을 수 없습니다.'}), 404

        def val(key, default_key):
            return data.get(key) if data.get(key) is not None else existing.get(default_key, '')

        start = val('startDate', 'start_date')
        end = val('endDate', 'end_date')
        period_text = data.get('periodText') or f'{start} ~ {end}'
        db.execute(
            """UPDATE projects SET
               project_name=?, contract_amount=?, start_date=?, end_date=?,
               period_text=?, client_name=?, contractor_name=?,
               location=?, description=?, updated_at=?, updated_by=?
               WHERE id=?""",
            (val('projectName', 'project_name'), val('contractAmount', 'contract_amount'),
             start, end, period_text,
             val('clientName', 'client_name'), val('contractorName', 'contractor_name'),
             val('location', 'location'), val('description', 'description'),
             now_iso(), user['name'] if user else '', target_id)
        )
        db.commit()
        projects = rows_to_list(db.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall())
        proj_info = next((p for p in projects if p['id'] == target_id), None)
        add_audit_log(user['id'] if user else '', user['name'] if user else '',
                      user['role'] if user else '', 'EDIT',
                      f"공사정보 수정: [공사명: {proj_info['project_name']}]")
        return jsonify({'success': True, 'projectInfo': proj_info, 'projects': projects})
    finally:
        db.close()


@app.route('/api/project-info/select', methods=['POST'])
def select_project():
    data = request.get_json()
    pid = data.get('projectId')
    db = get_db()
    try:
        target = row_to_dict(db.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone())
        if not target:
            return jsonify({'error': '해당 공사를 찾을 수 없습니다.'}), 404
        set_active_project_id(pid)
        projects = rows_to_list(db.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall())
        return jsonify({'success': True, 'projectInfo': target, 'projects': projects})
    finally:
        db.close()


@app.route('/api/project-info/<pid>', methods=['DELETE'])
def delete_project(pid):
    user_id = get_current_user_id()
    user = get_user(user_id)
    db = get_db()
    try:
        count = db.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
        if count <= 1:
            return jsonify({'error': '최소 1개 이상의 공사정보가 시스템에 유지되어야 합니다.'}), 400
        target = row_to_dict(db.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone())
        if not target:
            return jsonify({'error': '해당 공사를 찾을 수 없습니다.'}), 404
        db.execute("DELETE FROM projects WHERE id=?", (pid,))
        db.commit()
        active_id = request.form.get('projectId') or get_active_project_id() or ''
        if active_id == pid:
            first = row_to_dict(db.execute("SELECT id FROM projects ORDER BY updated_at DESC LIMIT 1").fetchone())
            if first:
                set_active_project_id(first['id'])
        projects = rows_to_list(db.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall())
        proj_info = next((p for p in projects if p['id'] == get_active_project_id()), projects[0] if projects else None)
        add_audit_log(user['id'] if user else '', user['name'] if user else '',
                      user['role'] if user else '', 'DELETE',
                      f"공사 정보 삭제: [{target['project_name']}]")
        return jsonify({'success': True, 'projectInfo': proj_info, 'projects': projects})
    finally:
        db.close()


@app.route('/api/project-info/batch-delete', methods=['POST'])
def batch_delete_projects():
    data = request.get_json()
    ids = data.get('projectIds', [])
    user = get_user(get_current_user_id())
    if not ids:
        return jsonify({'error': '삭제할 공사를 선택해주세요.'}), 400
    db = get_db()
    try:
        all_projects = rows_to_list(db.execute("SELECT * FROM projects").fetchall())
        remaining = [p for p in all_projects if p['id'] not in ids]
        if len(remaining) == 0:
            return jsonify({'error': '최소 1개 이상의 공사정보가 유지되어야 합니다.'}), 400
        deleted_names = [p['project_name'] for p in all_projects if p['id'] in ids]
        for pid in ids:
            db.execute("DELETE FROM projects WHERE id=?", (pid,))
        db.commit()
        active_id = request.form.get('projectId') or get_active_project_id() or ''
        if active_id in ids:
            set_active_project_id(remaining[0]['id'])
        projects = rows_to_list(db.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall())
        proj_info = next((p for p in projects if p['id'] == get_active_project_id()), projects[0] if projects else None)
        add_audit_log(user['id'] if user else '', user['name'] if user else '',
                      user['role'] if user else '', 'DELETE',
                      f"공사 정보 일괄 삭제 ({len(ids)}건): [{', '.join(deleted_names)}]")
        return jsonify({'success': True, 'projectInfo': proj_info, 'projects': projects})
    finally:
        db.close()


# ════════════════════════════════════════════════════════════
# 3. 근로자 이력정보 API
# ════════════════════════════════════════════════════════════
@app.route('/api/workers', methods=['GET'])
def get_workers():
    user_id = get_current_user_id()
    view_as = request.args.get('viewAsUserId', '').strip()
    u = get_user(user_id)
    if u and u.get('role') == 'admin' and view_as:
        user_id = view_as
    keyword  = request.args.get('keyword', '').strip()
    job_type = request.args.get('jobType', 'all')
    project_id = request.args.get('projectId', 'all')  # 관리자 필터
    db = get_db()
    try:
        sql = "SELECT * FROM workers WHERE project_id IN (SELECT id FROM projects WHERE status != 'completed')"
        params = []
        # 권한 기반 현장 필터
        assigned = get_user_assigned_project_ids(user_id) if user_id else None
        if assigned is not None:
            if project_id and project_id != 'all':
                if project_id not in assigned:
                    sql += " AND 1=0"
                else:
                    sql += " AND project_id=?"
                    params.append(project_id)
            else:
                if len(assigned) == 0:
                    sql += " AND 1=0"
                else:
                    placeholders = ','.join('?' * len(assigned))
                    sql += f" AND project_id IN ({placeholders})"
                    params.extend(assigned)
        else:
            if project_id and project_id != 'all':
                sql += " AND project_id=?"
                params.append(project_id)
        if keyword:
            sql += " AND (name LIKE ? OR nationality LIKE ?)"
            params += [f'%{keyword}%'] * 2
        if job_type and job_type != 'all':
            sql += " AND job_type=?"
            params.append(job_type)
        sql += " ORDER BY created_at DESC"
        workers = rows_to_list(db.execute(sql, params).fetchall())
        return jsonify({'success': True, 'workers': workers})
    finally:
        db.close()


@app.route('/api/workers', methods=['POST'])
def create_worker():
    if request.content_type and 'multipart/form-data' in request.content_type:
        user_id = get_current_user_id()
        name = request.form.get('name', '').strip()
        job_type = request.form.get('job_type', request.form.get('jobType', '')).strip()
        nationality = request.form.get('nationality', '대한민국')
        hire_date = request.form.get('hire_date', '')
        notes = request.form.get('notes', '')
        project_id_input = request.form.get('projectId', '')
        site_name_input = request.form.get('siteName', '')
    else:
        data = request.get_json() or {}
        user_id = get_current_user_id()
        name = data.get('name', '').strip()
        job_type = data.get('job_type', data.get('jobType', '')).strip()
        nationality = data.get('nationality', '대한민국')
        hire_date = data.get('hire_date', '')
        notes = data.get('notes', '')
        project_id_input = data.get('projectId', '')
        site_name_input = data.get('siteName', '')

    user = get_user(user_id)
    if not name:
        return jsonify({'error': '이름을 입력해주세요.'}), 400
        
    image_path = ''
    original_filename = ''
    if 'file' in request.files:
        f = request.files['file']
        if f and f.filename:
            original_filename = f.filename
            ext = os.path.splitext(f.filename)[1] or '.jpg'
            unique_name = f"wrk_{new_id('img')}{ext}"
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_name)
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            f.save(save_path)
            image_path = unique_name

    active_id = request.form.get('projectId') or get_active_project_id() or ''
    db = get_db()
    try:
        active_proj = row_to_dict(db.execute("SELECT * FROM projects WHERE id=?", (active_id,)).fetchone()) if active_id else None
        wid = new_id('wrk')
        n = now_iso()
        site_name = site_name_input or (active_proj['project_name'] if active_proj else '')
        # creator_id 및 image_path 컬럼 반영
        cols = {row[1] for row in db.execute("PRAGMA table_info(workers)").fetchall()}
        if 'creator_id' not in cols:
            db.execute("ALTER TABLE workers ADD COLUMN creator_id TEXT DEFAULT ''")
            db.commit()
        if 'image_path' not in cols:
            db.execute("ALTER TABLE workers ADD COLUMN image_path TEXT DEFAULT ''")
            db.commit()
        if 'original_filename' not in cols:
            db.execute("ALTER TABLE workers ADD COLUMN original_filename TEXT DEFAULT ''")
            db.commit()

        db.execute(
            "INSERT INTO workers (id, project_id, name, birth_date, gender, nationality, contact, job_type, site_name, created_at, updated_at, hire_date, notes, creator_id, image_path, original_filename) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (wid, project_id_input or active_id,
             name, '',        # birth_date
             '남',            # gender
             nationality,
             '',              # contact
             job_type, site_name, n, n,
             hire_date, notes, user['id'] if user else '', image_path, original_filename)
        )
        db.commit()
        worker = row_to_dict(db.execute("SELECT * FROM workers WHERE id=?", (wid,)).fetchone())
        add_audit_log(user['id'] if user else '', user['name'] if user else '',
                      user['role'] if user else '', 'EDIT',
                      f"신규 근로자 이력 등록: [성명: {name}, 직종: {job_type}]")
        return jsonify({'success': True, 'worker': worker})
    finally:
        db.close()


@app.route('/api/workers/<wid>', methods=['GET'])
def get_worker_one(wid):
    db = get_db()
    try:
        worker = row_to_dict(db.execute("SELECT * FROM workers WHERE id=?", (wid,)).fetchone())
        if not worker:
            return jsonify({'error': '근로자를 찾을 수 없습니다.'}), 404
        return jsonify({'success': True, 'worker': worker})
    finally:
        db.close()


@app.route('/api/workers/<wid>', methods=['PUT'])
def update_worker(wid):
    if request.content_type and 'multipart/form-data' in request.content_type:
        user_id = get_current_user_id()
        name_input = request.form.get('name')
        nationality_input = request.form.get('nationality')
        job_type_input = request.form.get('job_type', request.form.get('jobType'))
        hire_date_input = request.form.get('hire_date')
        notes_input = request.form.get('notes')
    else:
        data = request.get_json() or {}
        user_id = get_current_user_id()
        name_input = data.get('name')
        nationality_input = data.get('nationality')
        job_type_input = data.get('job_type', data.get('jobType'))
        hire_date_input = data.get('hire_date')
        notes_input = data.get('notes')

    user = get_user(user_id)
    
    db = get_db()
    try:
        worker = row_to_dict(db.execute("SELECT * FROM workers WHERE id=?", (wid,)).fetchone())
        if not worker:
            return jsonify({'error': '근로자 정보를 찾을 수 없습니다.'}), 404
            
        if user and user['role'] != 'admin' and worker.get('creator_id') != user['id']:
            return jsonify({'error': '권한이 없습니다.'}), 403
            
        image_path = worker.get('image_path', '')
        original_filename = worker.get('original_filename', '')
        delete_file = request.form.get('delete_file', 'false') == 'true'
        
        if delete_file:
            image_path = ''
            original_filename = ''

        if 'file' in request.files:
            f = request.files['file']
            if f and f.filename:
                original_filename = f.filename
                ext = os.path.splitext(f.filename)[1] or '.jpg'
                unique_name = f"wrk_{new_id('img')}{ext}"
                save_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_name)
                os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
                f.save(save_path)
                image_path = unique_name

        name = name_input or worker['name']
        nationality = nationality_input or worker.get('nationality','')
        job_type = job_type_input or worker.get('job_type','')
        hire_date = hire_date_input or worker.get('hire_date','')
        notes = notes_input if notes_input is not None else worker.get('notes','')
        
        # image_path 및 original_filename 컬럼 반영
        cols = {row[1] for row in db.execute("PRAGMA table_info(workers)").fetchall()}
        if 'image_path' not in cols:
            db.execute("ALTER TABLE workers ADD COLUMN image_path TEXT DEFAULT ''")
            db.commit()
        if 'original_filename' not in cols:
            db.execute("ALTER TABLE workers ADD COLUMN original_filename TEXT DEFAULT ''")
            db.commit()

        db.execute(
            """UPDATE workers SET name=?, nationality=?, job_type=?, hire_date=?, notes=?, image_path=?, original_filename=?, updated_at=? WHERE id=?""",
            (name, nationality, job_type, hire_date, notes, image_path, original_filename, now_iso(), wid)
        )
        db.commit()
        updated = row_to_dict(db.execute("SELECT * FROM workers WHERE id=?", (wid,)).fetchone())
        add_audit_log(user['id'] if user else '', user['name'] if user else '',
                      user['role'] if user else '', 'EDIT',
                      f"근로자 이력 수정: [성명: {name}, 직종: {job_type}]")
        return jsonify({'success': True, 'worker': updated})
    finally:
        db.close()


@app.route('/api/workers/download/<wid>', methods=['GET'])
def download_worker_file(wid):
    user_id = get_current_user_id()
    user = get_user(user_id)
    if not user:
        user = get_user()
    db = get_db()
    try:
        worker = row_to_dict(db.execute("SELECT * FROM workers WHERE id=?", (wid,)).fetchone())
        if not worker or not worker.get('image_path'):
            return jsonify({'error': '첨부파일이 존재하지 않습니다.'}), 404
        
        file_path = worker['image_path']
        original_name = worker.get('original_filename') or file_path
        
        # 안전한 파일 전송
        try:
            return send_from_directory(app.config['UPLOAD_FOLDER'], file_path, as_attachment=True, download_name=original_name)
        except Exception as e:
            return jsonify({'error': '파일을 읽을 수 없습니다.', 'details': str(e)}), 500
    finally:
        db.close()


@app.route('/api/workers/<wid>', methods=['DELETE'])
def delete_worker(wid):
    user_id = get_current_user_id()
    user = get_user(user_id)
    db = get_db()
    try:
        worker = row_to_dict(db.execute("SELECT * FROM workers WHERE id=?", (wid,)).fetchone())
        if not worker:
            return jsonify({'error': '근로자 정보를 찾을 수 없습니다.'}), 404
            
        if user and user['role'] != 'admin' and worker.get('creator_id') != user['id']:
            return jsonify({'error': '권한이 없습니다.'}), 403
        db.execute("DELETE FROM workers WHERE id=?", (wid,))
        db.commit()
        add_audit_log(user['id'] if user else '', user['name'] if user else '',
                      user['role'] if user else '', 'DELETE',
                      f"근로자 이력 삭제: [성명: {worker['name']}, 직종: {worker['job_type']}]")
        return jsonify({'success': True, 'message': '근로자 정보가 삭제되었습니다.'})
    finally:
        db.close()


# ════════════════════════════════════════════════════════════
# 4. 작업계획서 API
# ════════════════════════════════════════════════════════════
@app.route('/api/work-plans', methods=['GET'])
def get_work_plans():
    user_id  = get_current_user_id()
    keyword  = request.args.get('keyword', '').strip()
    plan_cat = request.args.get('planCategory', 'all')
    project_id = request.args.get('projectId', 'all')
    db = get_db()
    try:
        sql = "SELECT * FROM work_plans WHERE project_id IN (SELECT id FROM projects WHERE status != 'completed')"
        params = []
        assigned = get_user_assigned_project_ids(user_id) if user_id else None
        if assigned is not None:
            if project_id and project_id != 'all':
                if project_id not in assigned:
                    sql += " AND 1=0"
                else:
                    sql += " AND project_id=?"
                    params.append(project_id)
            else:
                if len(assigned) == 0:
                    sql += " AND 1=0"
                else:
                    placeholders = ','.join('?' * len(assigned))
                    sql += f" AND project_id IN ({placeholders})"
                    params.extend(assigned)
        else:
            if project_id and project_id != 'all':
                sql += " AND project_id=?"
                params.append(project_id)
        if keyword:
            sql += """ AND (site_name LIKE ? OR company_name LIKE ? OR
                       machinery_name LIKE ? OR vehicle_number LIKE ? OR usage_location LIKE ?)"""
            params += [f'%{keyword}%'] * 5
        if plan_cat and plan_cat != 'all':
            sql += " AND plan_category=?"
            params.append(plan_cat)
        sql += " ORDER BY created_at DESC"
        plans = rows_to_list(db.execute(sql, params).fetchall())
        # Convert heavy_handling to bool
        for p in plans:
            p['heavy_handling'] = bool(p['heavy_handling'])
        return jsonify({'success': True, 'workPlans': plans})
    finally:
        db.close()


@app.route('/api/work-plans', methods=['POST'])
def create_work_plan():
    data = request.get_json()
    user = get_user(get_current_user_id())
    active_id = request.form.get('projectId') or get_active_project_id() or ''
    db = get_db()
    try:
        active_proj = row_to_dict(db.execute("SELECT * FROM projects WHERE id=?", (active_id,)).fetchone()) if active_id else None
        wid = new_id('wp')
        n = now_iso()
        db.execute(
            """INSERT INTO work_plans (
                id, project_id, site_name, company_name, created_date, plan_category, 
                heavy_handling, machinery_name, equipment_plan_type, specification, 
                vehicle_number, equipment_year, registered_vendor, insurance_expiry_date, 
                inspection_validity_date, ndt_testing_date, training_date, usage_start_date, 
                usage_end_date, usage_location, creator_id, creator_name, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (wid, data.get('projectId') or active_id,
             data.get('siteName') or (active_proj['project_name'] if active_proj else ''),
             data.get('companyName') or (active_proj['contractor_name'] if active_proj else ''),
             data.get('createdDate') or n[:10],
             data.get('planCategory') or '차량계 건설기계',
             1 if data.get('heavyHandling') else 0,
             data.get('machineryName', ''), data.get('equipmentPlanType', ''),
             data.get('specification', ''), data.get('vehicleNumber', ''),
             data.get('equipmentYear', ''), data.get('registeredVendor', ''),
             data.get('insuranceExpiryDate', ''), data.get('inspectionValidityDate', ''),
             data.get('ndtTestingDate', ''), data.get('trainingDate', ''),
             data.get('usageStartDate', ''), data.get('usageEndDate', ''),
             data.get('usageLocation', ''),
             user['id'] if user else '', user['name'] if user else '',
             n, n)
        )
        db.commit()
        plan = row_to_dict(db.execute("SELECT * FROM work_plans WHERE id=?", (wid,)).fetchone())
        plan['heavy_handling'] = bool(plan['heavy_handling'])
        add_audit_log(user['id'] if user else '', user['name'] if user else '',
                      user['role'] if user else '', 'EDIT',
                      f"수기 작업계획서 작성: [장비명: {plan['machinery_name']}, 구분: {plan['plan_category']}]")
        return jsonify({'success': True, 'workPlan': plan})
    finally:
        db.close()


@app.route('/api/work-plans/<wid>', methods=['PUT'])
def update_work_plan(wid):
    data = request.get_json()
    user = get_user(get_current_user_id())
    db = get_db()
    try:
        plan = row_to_dict(db.execute("SELECT * FROM work_plans WHERE id=?", (wid,)).fetchone())
        if not plan:
            return jsonify({'error': '작업계획서를 찾을 수 없습니다.'}), 404

        def gv(key, db_key):
            return data[key] if key in data else plan[db_key]

        db.execute(
            """UPDATE work_plans SET
               site_name=?, company_name=?, created_date=?, plan_category=?,
               heavy_handling=?, machinery_name=?, equipment_plan_type=?, specification=?,
               vehicle_number=?, equipment_year=?, registered_vendor=?,
               insurance_expiry_date=?, inspection_validity_date=?, ndt_testing_date=?,
               training_date=?, usage_start_date=?, usage_end_date=?,
               usage_location=?, updated_at=? WHERE id=?""",
            (gv('siteName', 'site_name'), gv('companyName', 'company_name'),
             gv('createdDate', 'created_date'), gv('planCategory', 'plan_category'),
             1 if gv('heavyHandling', 'heavy_handling') else 0,
             gv('machineryName', 'machinery_name'), gv('equipmentPlanType', 'equipment_plan_type'),
             gv('specification', 'specification'), gv('vehicleNumber', 'vehicle_number'),
             gv('equipmentYear', 'equipment_year'), gv('registeredVendor', 'registered_vendor'),
             gv('insuranceExpiryDate', 'insurance_expiry_date'),
             gv('inspectionValidityDate', 'inspection_validity_date'),
             gv('ndtTestingDate', 'ndt_testing_date'), gv('trainingDate', 'training_date'),
             gv('usageStartDate', 'usage_start_date'), gv('usageEndDate', 'usage_end_date'),
             gv('usageLocation', 'usage_location'), now_iso(), wid)
        )
        db.commit()
        updated = row_to_dict(db.execute("SELECT * FROM work_plans WHERE id=?", (wid,)).fetchone())
        updated['heavy_handling'] = bool(updated['heavy_handling'])
        add_audit_log(user['id'] if user else '', user['name'] if user else '',
                      user['role'] if user else '', 'EDIT',
                      f"수기 작업계획서 수정: [장비명: {updated['machinery_name']}]")
        return jsonify({'success': True, 'workPlan': updated})
    finally:
        db.close()


@app.route('/api/work-plans/<wid>', methods=['DELETE'])
def delete_work_plan(wid):
    user_id = get_current_user_id()
    user = get_user(user_id)
    db = get_db()
    try:
        plan = row_to_dict(db.execute("SELECT * FROM work_plans WHERE id=?", (wid,)).fetchone())
        if not plan:
            return jsonify({'error': '작업계획서를 찾을 수 없습니다.'}), 404
        db.execute("DELETE FROM work_plans WHERE id=?", (wid,))
        db.commit()
        add_audit_log(user['id'] if user else '', user['name'] if user else '',
                      user['role'] if user else '', 'DELETE',
                      f"수기 작업계획서 삭제: [장비명: {plan['machinery_name']}]")
        return jsonify({'success': True, 'message': '작업계획서가 삭제되었습니다.'})
    finally:
        db.close()


# ════════════════════════════════════════════════════════════
# 5. TBM 일지 API
# ════════════════════════════════════════════════════════════
@app.route('/api/tbm-logs', methods=['GET'])
def get_tbm_logs():
    user_id    = get_current_user_id()
    keyword    = request.args.get('keyword', '').strip()
    project_id = request.args.get('projectId', 'all')
    db = get_db()
    try:
        sql = "SELECT * FROM tbm_logs WHERE project_id IN (SELECT id FROM projects WHERE status != 'completed')"
        params = []
        assigned = get_user_assigned_project_ids(user_id) if user_id else None
        if assigned is not None:
            if project_id and project_id != 'all':
                if project_id not in assigned:
                    sql += " AND 1=0"
                else:
                    sql += " AND project_id=?"
                    params.append(project_id)
            else:
                if len(assigned) == 0:
                    sql += " AND 1=0"
                else:
                    placeholders = ','.join('?' * len(assigned))
                    sql += f" AND project_id IN ({placeholders})"
                    params.extend(assigned)
        else:
            if project_id and project_id != 'all':
                sql += " AND project_id=?"
                params.append(project_id)
        if keyword:
            sql += """ AND (project_name LIKE ? OR instructor LIKE ? OR
                       work_details_hazards LIKE ? OR safety_measures LIKE ?)"""
            params += [f'%{keyword}%'] * 4
        sql += " ORDER BY created_at DESC"
        logs = rows_to_list(db.execute(sql, params).fetchall())
        return jsonify({'success': True, 'tbmLogs': logs})
    finally:
        db.close()


@app.route('/api/tbm-logs', methods=['POST'])
def create_tbm_log():
    data = request.get_json()
    user = get_user(get_current_user_id())
    proj_name = (data.get('projectName') or '').strip()
    instructor = (data.get('instructor') or '').strip()
    hazards = (data.get('workDetailsHazards') or '').strip()
    measures = (data.get('safetyMeasures') or '').strip()
    if not proj_name or not instructor or not hazards or not measures:
        return jsonify({'error': '필수 항목(공사명, 교육자, 작업사항/위험요인, 안전대책)을 입력해주세요.'}), 400
    active_id = request.form.get('projectId') or get_active_project_id() or ''
    db = get_db()
    try:
        active_proj = row_to_dict(db.execute("SELECT * FROM projects WHERE id=?", (active_id,)).fetchone()) if active_id else None
        tid = new_id('tbm')
        n = now_iso()
        period = data.get('projectPeriod') or (active_proj['period_text'] if active_proj else '')
        db.execute(
            """INSERT INTO tbm_logs (
                id, project_id, project_name, project_period, instructor, 
                work_details_hazards, safety_measures, special_notes, created_date, 
                creator_id, creator_name, created_at, updated_at, image_path
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (tid, data.get('projectId') or active_id,
             proj_name, period, instructor, hazards, measures,
             (data.get('specialNotes') or '').strip(),
             data.get('createdDate') or n[:10],
             user['id'] if user else '', user['name'] if user else '',
             n, n, '')
        )
        db.commit()
        log = row_to_dict(db.execute("SELECT * FROM tbm_logs WHERE id=?", (tid,)).fetchone())
        add_audit_log(user['id'] if user else '', user['name'] if user else '',
                      user['role'] if user else '', 'UPLOAD',
                      f"TBM 일지 수기 작성/등록: [공사명: {proj_name}, 교육자: {instructor}]")
        return jsonify({'success': True, 'tbmLog': log})
    finally:
        db.close()


@app.route('/api/tbm-logs/<tid>', methods=['PUT'])
def update_tbm_log(tid):
    data = request.get_json()
    user = get_user(get_current_user_id())
    db = get_db()
    try:
        tbm = row_to_dict(db.execute("SELECT * FROM tbm_logs WHERE id=?", (tid,)).fetchone())
        if not tbm:
            return jsonify({'error': 'TBM 일지를 찾을 수 없습니다.'}), 404

        def gv(key, db_key):
            return data[key] if key in data else tbm[db_key]

        db.execute(
            """UPDATE tbm_logs SET
               project_name=?, project_period=?, instructor=?,
               work_details_hazards=?, safety_measures=?, special_notes=?,
               created_date=?, updated_at=? WHERE id=?""",
            (gv('projectName', 'project_name'), gv('projectPeriod', 'project_period'),
             gv('instructor', 'instructor'), gv('workDetailsHazards', 'work_details_hazards'),
             gv('safetyMeasures', 'safety_measures'), gv('specialNotes', 'special_notes'),
             gv('createdDate', 'created_date'), now_iso(), tid)
        )
        db.commit()
        updated = row_to_dict(db.execute("SELECT * FROM tbm_logs WHERE id=?", (tid,)).fetchone())
        add_audit_log(user['id'] if user else '', user['name'] if user else '',
                      user['role'] if user else '', 'EDIT',
                      f"TBM 일지 수정: [공사명: {updated['project_name']}]")
        return jsonify({'success': True, 'tbmLog': updated})
    finally:
        db.close()


@app.route('/api/tbm-logs/<tid>', methods=['DELETE'])
def delete_tbm_log(tid):
    user_id = get_current_user_id()
    user = get_user(user_id)
    db = get_db()
    try:
        tbm = row_to_dict(db.execute("SELECT * FROM tbm_logs WHERE id=?", (tid,)).fetchone())
        if not tbm:
            return jsonify({'error': 'TBM 일지를 찾을 수 없습니다.'}), 404
        db.execute("DELETE FROM tbm_logs WHERE id=?", (tid,))
        db.commit()
        add_audit_log(user['id'] if user else '', user['name'] if user else '',
                      user['role'] if user else '', 'DELETE',
                      f"TBM 일지 삭제: [공사명: {tbm['project_name']}]")
        return jsonify({'success': True, 'message': 'TBM 일지가 삭제되었습니다.'})
    finally:
        db.close()


# ════════════════════════════════════════════════════════════
# 6. 문서 관리 API
# ════════════════════════════════════════════════════════════
@app.route('/api/documents', methods=['GET'])
def get_documents():
    user_id = get_current_user_id()
    keyword = request.args.get('keyword', '').strip()
    file_type = request.args.get('fileType', 'all')
    main_cat = request.args.get('mainCategory', 'all')
    sub_cat = request.args.get('subCategory', 'all')
    visibility = request.args.get('visibility', 'all')
    project_id = request.args.get('projectId', 'all')
    sort_by = request.args.get('sortBy', 'created_at')
    sort_order = request.args.get('sortOrder', 'desc')

    user = get_user(user_id)
    db = get_db()
    try:
        deleted = request.args.get('deleted', 'false')
        is_del = 1 if deleted.lower() == 'true' else 0
        sql = "SELECT * FROM documents WHERE is_deleted=?"
        params = [is_del]
        if project_id and project_id != 'all':
            sql += " AND (project_id=? OR project_id IS NULL OR project_id='')"
            params.append(project_id)
        if keyword:
            sql += """ AND (title LIKE ? OR original_file_name LIKE ? OR
                       main_category LIKE ? OR sub_category LIKE ? OR
                       tags LIKE ? OR uploader_name LIKE ? OR ai_summary LIKE ?)"""
            params += [f'%{keyword}%'] * 7
        if file_type and file_type != 'all':
            sql += " AND file_type=?"
            params.append(file_type)
        if main_cat and main_cat not in ('all', '전체'):
            sql += " AND main_category=?"
            params.append(main_cat)
        if sub_cat and sub_cat not in ('all', '전체'):
            sql += " AND sub_category=?"
            params.append(sub_cat)
        if visibility and visibility != 'all':
            sql += " AND visibility=?"
            params.append(visibility)

        col_map = {
            'createdAt': 'created_at', 'title': 'title', 'fileSize': 'file_size',
            'viewCount': 'view_count', 'downloadCount': 'download_count'
        }
        col = col_map.get(sort_by, 'created_at')
        order = 'ASC' if sort_order == 'asc' else 'DESC'
        sql += f" ORDER BY {col} {order}"

        rows = db.execute(sql, params).fetchall()
        docs = []
        for row in rows:
            d = doc_row_to_dict(row)
            if user and not can_access_doc(d, user):
                continue
            docs.append(d)
        return jsonify({'success': True, 'total': len(docs), 'documents': docs})
    finally:
        db.close()


@app.route('/api/documents/upload', methods=['POST'])
def upload_document():
    user_id = request.form.get('uploaderId') or get_current_user_id()
    user = get_user(user_id)
    if not user:
        user = get_user()

    title = request.form.get('title', '')
    main_category = request.form.get('mainCategory', '공사정보')
    sub_category = request.form.get('subCategory', '')
    category = request.form.get('category', sub_category)
    tags_raw = request.form.get('tags', '[]')
    visibility = request.form.get('visibility', 'all')
    target_dept = request.form.get('targetDepartment', '')
    project_id = request.form.get('projectId') or get_active_project_id() or ''

    active_id = request.form.get('projectId') or get_active_project_id() or ''
    db = get_db()
    try:
        active_proj = row_to_dict(db.execute("SELECT * FROM projects WHERE id=?", (project_id or active_id,)).fetchone()) if (project_id or active_id) else None
        proj_name = active_proj['project_name'] if active_proj else ''

        file_path = ''
        original_file_name = ''
        file_size = 0
        mime_type = 'application/octet-stream'
        file_type_str = 'other'

        if 'file' in request.files:
            f = request.files['file']
            if f and f.filename:
                original_file_name = f.filename
                if not title:
                    title = original_file_name
                safe_name = secure_filename(f.filename)
                unique_name = f"{new_id('file')}_{safe_name}"
                save_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_name)
                os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
                f.save(save_path)
                file_size = os.path.getsize(save_path)
                file_path = unique_name
                mime_type = f.content_type or mimetypes.guess_type(safe_name)[0] or 'application/octet-stream'
                file_type_str = detect_file_type(original_file_name, mime_type)

        if not original_file_name:
            original_file_name = title or 'unknown'
        if not title:
            title = original_file_name

        try:
            tags = json.loads(tags_raw) if tags_raw else []
        except Exception:
            tags = [t.strip() for t in tags_raw.split(',') if t.strip()]

        doc_id = new_id('doc')
        n = now_iso()
        tags_str = json.dumps(tags, ensure_ascii=False)

        db.execute(
            """INSERT INTO documents (
                id, project_id, project_name, title, original_file_name, file_type, 
                mime_type, file_size, main_category, sub_category, category, tags, 
                uploader_id, uploader_name, uploader_role, uploader_department, 
                visibility, target_department, created_at, updated_at, file_path, 
                download_count, view_count, ai_summary, ai_key_insights, 
                ai_extracted_text, ai_detected_columns, ai_auto_tags, is_deleted
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (doc_id, project_id, proj_name,
             title, original_file_name, file_type_str, mime_type, file_size,
             main_category, sub_category or category, category,
             tags_str,
             user['id'], user['name'], user['role'], user['department'],
             visibility, target_dept,
             n, n, file_path, 0, 1,
             f"{title} 파일이 서버에 저장되었습니다.", '[]', '', '[]', '[]', 0)
        )
        db.commit()
        doc = doc_row_to_dict(db.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone())
        add_audit_log(user['id'], user['name'], user['role'], 'UPLOAD',
                      f"신규 문서 업로드 완료 [{title}] (타입: {file_type_str})",
                      doc_id, title)
        return jsonify({'success': True, 'document': doc})
    except Exception as e:
        print(f'[Error in upload]: {e}')
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()


@app.route('/api/documents/<doc_id>', methods=['GET'])
def get_document(doc_id):
    user_id = get_current_user_id()
    user = get_user(user_id)
    db = get_db()
    try:
        row = db.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        if not row:
            return jsonify({'error': '문서를 찾을 수 없습니다.'}), 404
        doc = doc_row_to_dict(row)
        if user and not can_access_doc(doc, user):
            return jsonify({'error': '해당 문서에 접근할 권한이 없습니다.'}), 403
        db.execute("UPDATE documents SET view_count=view_count+1 WHERE id=?", (doc_id,))
        db.commit()
        doc['view_count'] += 1
        if user:
            add_audit_log(user['id'], user['name'], user['role'], 'VIEW',
                          f"문서 상세 조회: [{doc['title']}]", doc_id, doc['title'])
        return jsonify({'success': True, 'document': doc})
    except Exception as e:
        print(f'[Error in upload]: {e}')
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()


@app.route('/api/documents/<doc_id>', methods=['PUT'])
def update_document(doc_id):
    data = request.get_json()
    user = get_user(get_current_user_id())
    db = get_db()
    try:
        row = db.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        if not row:
            return jsonify({'error': '문서를 찾을 수 없습니다.'}), 404
        doc = doc_row_to_dict(row)
        if user and user['role'] != 'admin' and doc.get('uploader_id') != user['id']:
            return jsonify({'error': '문서 수정 권한이 없습니다.'}), 403
        title = data.get('title') or doc['title']
        category = data.get('category') or doc['category']
        tags = data.get('tags') or doc.get('tags', [])
        visibility = data.get('visibility') or doc['visibility']
        target_dept = data.get('targetDepartment') or doc.get('target_department', '')
        db.execute(
            """UPDATE documents SET title=?, category=?, sub_category=?, tags=?,
               visibility=?, target_department=?, updated_at=? WHERE id=?""",
            (title, category, category, json.dumps(tags, ensure_ascii=False),
             visibility, target_dept, now_iso(), doc_id)
        )
        db.commit()
        updated = doc_row_to_dict(db.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone())
        if user:
            add_audit_log(user['id'], user['name'], user['role'], 'EDIT',
                          f"문서 메타데이터 수정 [{title}]", doc_id, title)
        return jsonify({'success': True, 'document': updated})
    finally:
        db.close()


@app.route('/api/documents/bulk-restore', methods=['POST'])
def bulk_restore_documents():
    data = request.get_json() or {}
    user_id = get_current_user_id()
    doc_ids = data.get('docIds', [])
    user = get_user(user_id)
    
    if not doc_ids:
        return jsonify({'error': '선택된 문서가 없습니다.'}), 400
        
    db = get_db()
    try:
        placeholders = ','.join('?' * len(doc_ids))
        
        # 권한 확인
        if user and user['role'] != 'admin':
            rows = db.execute(f"SELECT uploader_id FROM documents WHERE id IN ({placeholders})", doc_ids).fetchall()
            for row in rows:
                if row['uploader_id'] != user['id']:
                    return jsonify({'error': '복원 권한이 없는 문서가 포함되어 있습니다.'}), 403
                    
        db.execute(f"UPDATE documents SET is_deleted=0 WHERE id IN ({placeholders})", doc_ids)
        db.commit()
        
        if user:
            add_audit_log(user['id'], user['name'], user['role'], 'RESTORE',
                          f"문서 {len(doc_ids)}건 일괄 복원", 'bulk', '')
                          
        return jsonify({'success': True})
    finally:
        db.close()

@app.route('/api/documents/delete-multiple', methods=['DELETE'])
def delete_multiple_documents():
    data = request.get_json() or {}
    user_id = get_current_user_id()
    doc_ids = data.get('docIds', [])
    user = get_user(user_id)
    
    if not doc_ids:
        return jsonify({'error': '선택된 문서가 없습니다.'}), 400
        
    db = get_db()
    try:
        placeholders = ','.join('?' * len(doc_ids))
        
        # 권한 확인
        if user and user['role'] != 'admin':
            rows = db.execute(f"SELECT uploader_id FROM documents WHERE id IN ({placeholders})", doc_ids).fetchall()
            for row in rows:
                if row['uploader_id'] != user['id']:
                    return jsonify({'error': '삭제 권한이 없는 문서가 포함되어 있습니다.'}), 403
                    
        hard_delete = data.get('hard', False)
        if hard_delete:
            # 완전 삭제 모드 (파일 포함)
            rows = db.execute(f"SELECT file_path FROM documents WHERE id IN ({placeholders})", doc_ids).fetchall()
            for row in rows:
                if row['file_path']:
                    full_path = os.path.join(app.config['UPLOAD_FOLDER'], row['file_path'])
                    if os.path.exists(full_path):
                        try:
                            os.remove(full_path)
                        except:
                            pass
            db.execute(f"DELETE FROM documents WHERE id IN ({placeholders})", doc_ids)
        else:
            # 휴지통 이동 모드 (Soft Delete)
            db.execute(f"UPDATE documents SET is_deleted=1 WHERE id IN ({placeholders})", doc_ids)
            
        db.commit()
        
        if user:
            add_audit_log(user['id'], user['name'], user['role'], 'DELETE',
                          f"문서 {len(doc_ids)}건 일괄 삭제", 'bulk', '')
                          
        return jsonify({'success': True})
    finally:
        db.close()

@app.route('/api/documents/<doc_id>/restore', methods=['POST'])
def restore_document(doc_id):
    data = request.get_json() or {}
    user_id = get_current_user_id()
    user = get_user(user_id)
    db = get_db()
    try:
        row = db.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        if not row:
            return jsonify({'error': '문서를 찾을 수 없습니다.'}), 404
        doc = row_to_dict(row)
        if user and user['role'] != 'admin' and doc.get('uploader_id') != user['id']:
            return jsonify({'error': '문서 복원 권한이 없습니다.'}), 403
            
        db.execute("UPDATE documents SET is_deleted=0 WHERE id=?", (doc_id,))
        db.commit()
        if user:
            add_audit_log(user['id'], user['name'], user['role'], 'RESTORE',
                          f"문서 복원 [{doc['title']}]", doc_id, doc['title'])
        return jsonify({'success': True})
    finally:
        db.close()

@app.route('/api/documents/<doc_id>', methods=['DELETE'])
def delete_document(doc_id):
    user_id = get_current_user_id()
    user = get_user(user_id)
    db = get_db()
    try:
        row = db.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        if not row:
            return jsonify({'error': '문서를 찾을 수 없습니다.'}), 404
        doc = row_to_dict(row)
        if user and user['role'] != 'admin' and doc.get('uploader_id') != user['id']:
            return jsonify({'error': '문서 삭제 권한이 없습니다.'}), 403
        hard_delete = request.args.get('hard', 'false').lower() == 'true'
        if hard_delete:
            if doc.get('file_path'):
                fp = os.path.join(app.config['UPLOAD_FOLDER'], doc['file_path'])
                if os.path.exists(fp):
                    try:
                        os.remove(fp)
                    except:
                        pass
            db.execute("DELETE FROM documents WHERE id=?", (doc_id,))
        else:
            db.execute("UPDATE documents SET is_deleted=1 WHERE id=?", (doc_id,))
        db.commit()
        if user:
            add_audit_log(user['id'], user['name'], user['role'], 'DELETE',
                          f"문서 삭제 완료 [{doc['title']}]", doc_id, doc['title'])
        return jsonify({'success': True, 'message': '문서가 성공적으로 삭제되었습니다.'})
    finally:
        db.close()


@app.route('/api/documents/<doc_id>/download', methods=['POST'])
def download_document(doc_id):
    data = request.get_json() or {}
    user = get_user(get_current_user_id())
    db = get_db()
    try:
        row = db.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        if not row:
            return jsonify({'error': '문서를 찾을 수 없습니다.'}), 404
        db.execute("UPDATE documents SET download_count=download_count+1 WHERE id=?", (doc_id,))
        db.commit()
        doc = row_to_dict(row)
        if user:
            add_audit_log(user['id'], user['name'], user['role'], 'DOWNLOAD',
                          f"문서 다운로드 [{doc['title']}]", doc_id, doc['title'])
        return jsonify({'success': True, 'downloadCount': doc['download_count'] + 1,
                        'filePath': doc.get('file_path', '')})
    finally:
        db.close()


# ════════════════════════════════════════════════════════════
# 7. 감사 로그 API
# ════════════════════════════════════════════════════════════
@app.route('/api/audit-logs', methods=['GET'])
def get_audit_logs():
    user_id = get_current_user_id()
    user = get_user(user_id)
    db = get_db()
    try:
        if user and user['role'] == 'admin':
            logs = rows_to_list(db.execute(
                "SELECT * FROM audit_logs ORDER BY timestamp DESC LIMIT 500"
            ).fetchall())
        elif user:
            logs = rows_to_list(db.execute(
                "SELECT * FROM audit_logs WHERE user_id=? ORDER BY timestamp DESC LIMIT 200",
                (user['id'],)
            ).fetchall())
        else:
            logs = []
        return jsonify({'success': True, 'logs': logs})
    finally:
        db.close()


# ════════════════════════════════════════════════════════════
# 8. 대시보드 통계 API
# ════════════════════════════════════════════════════════════
@app.route('/api/stats', methods=['GET'])
def get_stats():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({'error': '인증이 필요합니다.'}), 401
    user = get_user(user_id)
    today = datetime.now().date().isoformat()
    db = get_db()
    try:
        is_admin = (user and user.get('role') == 'admin')
        
        if is_admin:
            # 관리자용: 전체 데이터 
            docs_cnt = db.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            tbm_cnt = db.execute("SELECT COUNT(*) FROM tbm_logs").fetchone()[0]
            plan_cnt = db.execute("SELECT COUNT(*) FROM workplans").fetchone()[0]
            try:
                daily_cnt = db.execute("SELECT COUNT(*) FROM daily_reports").fetchone()[0]
            except:
                daily_cnt = 0
            try:
                risk_cnt = db.execute("SELECT COUNT(*) FROM risk_assessments").fetchone()[0]
            except:
                risk_cnt = 0
            
            # 전체 문서 = 문서관리 + TBM + 작업계획서 + 작업일보 + 위험성평가
            total_docs = docs_cnt + tbm_cnt + plan_cnt + daily_cnt + risk_cnt
            
            total_bytes = db.execute("SELECT COALESCE(SUM(file_size),0) FROM documents").fetchone()[0]
            excel_cnt = db.execute("SELECT COUNT(*) FROM documents WHERE file_type='excel'").fetchone()[0]
            image_cnt = db.execute("SELECT COUNT(*) FROM documents WHERE file_type='image'").fetchone()[0]
            pdf_cnt = db.execute("SELECT COUNT(*) FROM documents WHERE file_type='pdf'").fetchone()[0]
            other_cnt = db.execute("SELECT COUNT(*) FROM documents WHERE file_type NOT IN ('excel','image','pdf')").fetchone()[0]
            today_cnt = db.execute("SELECT COUNT(*) FROM documents WHERE created_at LIKE ?", (f'{today}%',)).fetchone()[0]
            total_dl = db.execute("SELECT COALESCE(SUM(download_count),0) FROM documents").fetchone()[0]
            
            user_cnt = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            worker_cnt = db.execute("SELECT COUNT(*) FROM workers").fetchone()[0]
            proj_cnt = db.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
        else:
            # 일반 직원용: 본인 데이터 기준 
            docs_cnt = db.execute("SELECT COUNT(*) FROM documents WHERE uploader_id=?", (user_id,)).fetchone()[0]
            try:
                tbm_cnt = db.execute("SELECT COUNT(*) FROM tbm_logs WHERE creator_id=?", (user_id,)).fetchone()[0]
            except:
                tbm_cnt = 0
            try:
                plan_cnt = db.execute("SELECT COUNT(*) FROM workplans WHERE creator_id=?", (user_id,)).fetchone()[0]
            except:
                plan_cnt = 0
            try:
                daily_cnt = db.execute("SELECT COUNT(*) FROM daily_reports WHERE creator_id=?", (user_id,)).fetchone()[0]
            except:
                daily_cnt = 0
            try:
                risk_cnt = db.execute("SELECT COUNT(*) FROM risk_assessments WHERE creator_id=?", (user_id,)).fetchone()[0]
            except:
                risk_cnt = 0
            
            # 전체 문서 = 본인이 작성한 (문서관리 + TBM + 작업계획서 + 작업일보 + 위험성평가)
            total_docs = docs_cnt + tbm_cnt + plan_cnt + daily_cnt + risk_cnt

            total_bytes = db.execute("SELECT COALESCE(SUM(file_size),0) FROM documents WHERE uploader_id=?", (user_id,)).fetchone()[0]
            excel_cnt = db.execute("SELECT COUNT(*) FROM documents WHERE file_type='excel' AND uploader_id=?", (user_id,)).fetchone()[0]
            image_cnt = db.execute("SELECT COUNT(*) FROM documents WHERE file_type='image' AND uploader_id=?", (user_id,)).fetchone()[0]
            pdf_cnt = db.execute("SELECT COUNT(*) FROM documents WHERE file_type='pdf' AND uploader_id=?", (user_id,)).fetchone()[0]
            other_cnt = db.execute("SELECT COUNT(*) FROM documents WHERE file_type NOT IN ('excel','image','pdf') AND uploader_id=?", (user_id,)).fetchone()[0]
            today_cnt = db.execute("SELECT COUNT(*) FROM documents WHERE created_at LIKE ? AND uploader_id=?", (f'{today}%', user_id)).fetchone()[0]
            total_dl = db.execute("SELECT COALESCE(SUM(download_count),0) FROM documents WHERE uploader_id=?", (user_id,)).fetchone()[0]
            
            user_cnt = 0 # 일반 직원은 사용자 수를 볼 필요가 없거나 0으로 처리
            
            try:
                worker_cnt = db.execute("SELECT COUNT(*) FROM workers WHERE creator_id=?", (user_id,)).fetchone()[0]
            except:
                worker_cnt = 0
            
            assigned = get_user_assigned_project_ids(user_id) or []
            if len(assigned) == 0:
                proj_cnt = 0
            else:
                placeholders = ','.join('?' * len(assigned))
                proj_cnt = db.execute(f"SELECT COUNT(*) FROM projects WHERE id IN ({placeholders})", assigned).fetchone()[0]

        return jsonify({
            'success': True,
            'stats': {
                'totalDocuments': total_docs, 'totalStorageBytes': total_bytes,
                'excelCount': excel_cnt, 'imageCount': image_cnt,
                'pdfCount': pdf_cnt, 'otherCount': other_cnt,
                'totalUploadsToday': today_cnt, 'totalDownloads': total_dl,
                'activeUsersCount': user_cnt, 'workerCount': worker_cnt,
                'projectCount': proj_cnt, 'tbmCount': tbm_cnt, 'workPlanCount': plan_cnt,
            }
        })
    finally:
        db.close()


# ════════════════════════════════════════════════════════════

# ════════════════════════════════════════════════════════════
# 8-1. 대시보드 최근 등록된 글 통합 API
# ════════════════════════════════════════════════════════════
@app.route('/api/dashboard/recent', methods=['GET'])
def get_dashboard_recent():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({'error': '인증이 필요합니다.'}), 401
    user = get_user(user_id)
    db = get_db()
    try:
        items = []
        # 1. 공용 예외 (공지, 문서 관리) - 모두에게 노출
        # (단, 사용자가 명시한 "관리자가 등록한" 조건을 엄격히 적용하여 혼입 방지)
        notices = db.execute(
            "SELECT '공지' as type, title, author_name, created_at, file_name, file_path "
            "FROM notices "
            "WHERE author_id IN (SELECT id FROM users WHERE role='admin')"
        ).fetchall()
        
        docs = db.execute(
            "SELECT '문서 관리' as type, title, uploader_name as author_name, created_at, original_file_name as file_name, file_path "
            "FROM documents "
            "WHERE is_deleted=0 AND uploader_role='admin'"
        ).fetchall()
        
        for r in notices + docs:
            items.append(dict(r))
            
        # 2. 각 모듈 데이터 수집
        queries = [
            ("TBM", "SELECT 'TBM' as type, work_details_hazards as title, creator_name as author_name, created_at, '' as file_name, image_path as file_path FROM tbm_logs"),
            ("작업계획서", "SELECT '작업계획서' as type, work_content as title, manager_name as author_name, created_at, '' as file_name, image_path as file_path FROM workplans"),
            ("작업일보", "SELECT '작업일보' as type, work_content as title, manager_name as author_name, created_at, '' as file_name, image_path as file_path FROM daily_reports"),
            ("위험성평가", "SELECT '위험성평가' as type, task_name as title, evaluator as author_name, created_at, file_name, file_path FROM risk_assessments")
        ]
        
        for q_type, q_sql in queries:
            if user and user.get('role') == 'admin':
                rows = db.execute(q_sql).fetchall()
            else:
                rows = db.execute(f"{q_sql} WHERE creator_id=?", (user_id,)).fetchall()
                
            for r in rows:
                items.append(dict(r))
                
        # 3. 통합 정렬 (created_at 최신순)
        items.sort(key=lambda x: x['created_at'], reverse=True)
        
        return jsonify({'success': True, 'items': items[:10]})
    finally:
        db.close()


# 9. 카테고리 목록 API
# ════════════════════════════════════════════════════════════
@app.route('/api/categories', methods=['GET'])
def get_categories():
        return jsonify({'success': True, 'categories': CATEGORY_MAP})


# ════════════════════════════════════════════════════════════
# 10. 단순화 TBM API  /api/tbm
# ════════════════════════════════════════════════════════════
@app.route('/api/tbm', methods=['GET'])
def simple_get_tbm():
    user_id = get_current_user_id()
    view_as = request.args.get('viewAsUserId', '').strip()
    u = get_user(user_id)
    if u and u.get('role') == 'admin' and view_as:
        user_id = view_as
    project_id = request.args.get('projectId', 'all')
    db = get_db()
    try:
        assigned = get_user_assigned_project_ids(user_id) if user_id else []
        sql = "SELECT * FROM tbm_logs WHERE project_id IN (SELECT id FROM projects WHERE status != 'completed')"
        params = []
        if assigned is not None:
            if project_id and project_id != 'all':
                if project_id not in assigned:
                    sql += " AND 1=0"
                else:
                    sql += " AND project_id=?"
                    params.append(project_id)
            else:
                if len(assigned) == 0:
                    sql += " AND 1=0"
                else:
                    placeholders = ','.join('?' * len(assigned))
                    sql += f" AND project_id IN ({placeholders})"
                    params.extend(assigned)
        else:
            if project_id and project_id != 'all':
                sql += " AND project_id=?"
                params.append(project_id)
        sql += " ORDER BY created_at DESC"
        logs = rows_to_list(db.execute(sql, params).fetchall())
        return jsonify({'success': True, 'tbm_logs': logs})
    finally:
        db.close()

@app.route('/api/tbm', methods=['POST'])
def simple_create_tbm():
    user = get_user(get_current_user_id())
    active_id = request.form.get('projectId') or get_active_project_id() or ''
    
    image_path = ''
    files = request.files.getlist('files')
    if not files:
        f = request.files.get('file')
        if f and f.filename: files = [f]
    saved = []
    for f in files:
        if f and f.filename and allowed_file(f.filename):
            ext = (os.path.splitext(f.filename)[1] or '').lower()
            unique_name = f"tbm_{new_id('img')}{ext}"
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_name)
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            f.save(save_path)
            
            if ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif']:
                try:
                    img = Image.open(save_path)
                    img.thumbnail((1200, 1200))
                    img.save(save_path, optimize=True, quality=85)
                except Exception:
                    pass
            saved.append(unique_name)
    if saved:
        image_path = ','.join(saved)

    db = get_db()
    try:
        tid = new_id('tbm')
        n = now_iso()
        proj = row_to_dict(db.execute("SELECT * FROM projects WHERE id=?", (active_id,)).fetchone()) if active_id else None
        
        # image_path 컬럼 추가 반영
        cols = {row[1] for row in db.execute("PRAGMA table_info(tbm_logs)").fetchall()}
        if 'image_path' not in cols:
            db.execute("ALTER TABLE tbm_logs ADD COLUMN image_path TEXT DEFAULT ''")
            db.commit()

        db.execute(
            "INSERT INTO tbm_logs (id, project_id, project_name, project_period, instructor, work_details_hazards, safety_measures, special_notes, created_date, creator_id, creator_name, created_at, updated_at, image_path) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (tid, active_id,
             proj['project_name'] if proj else '',
             proj['period_text'] if proj else '',
             user['name'] if user else '',
             request.form.get('work_details_hazards',''),
             request.form.get('safety_measures',''),
             request.form.get('special_notes',''),
             request.form.get('created_date', n[:10]),
             user['id'] if user else '', user['name'] if user else '',
             n, n, image_path)
        )
        db.commit()
        log = row_to_dict(db.execute("SELECT * FROM tbm_logs WHERE id=?", (tid,)).fetchone())
        if user:
            add_audit_log(user['id'], user['name'], user['role'], 'EDIT', f"TBM 작성: {request.form.get('created_date','')}")
        return jsonify({'success': True, 'tbm_log': log})
    except Exception as e:
        print(f'[Error in upload]: {e}')
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

@app.route('/api/tbm/<tid>', methods=['GET'])
def simple_get_tbm_one(tid):
    db = get_db()
    try:
        log = row_to_dict(db.execute("SELECT * FROM tbm_logs WHERE id=?", (tid,)).fetchone())
        return jsonify({'success': True, 'tbm_log': log})
    except Exception as e:
        print(f'[Error in upload]: {e}')
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

@app.route('/api/tbm/<tid>', methods=['PUT'])
def simple_update_tbm(tid):
    user = get_user(get_current_user_id())
    
    image_path = None
    files = request.files.getlist('files')
    if not files:
        f = request.files.get('file')
        if f and f.filename: files = [f]
    saved = []
    for f in files:
        if f and f.filename and allowed_file(f.filename):
            ext = (os.path.splitext(f.filename)[1] or '').lower()
            unique_name = f"tbm_{new_id('img')}{ext}"
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_name)
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            f.save(save_path)
            
            if ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif']:
                try:
                    img = Image.open(save_path)
                    img.thumbnail((1200, 1200))
                    img.save(save_path, optimize=True, quality=85)
                except Exception:
                    pass
            saved.append(unique_name)
            
    deleted_files = [f.strip() for f in request.form.get('deleted_files', '').split(',') if f.strip()]
    db_tmp = get_db()
    try:
        old = row_to_dict(db_tmp.execute("SELECT image_path FROM tbm_logs WHERE id=?", (tid,)).fetchone())
        old_imgs = (old or {}).get('image_path', '')
        final_old_imgs = [img for img in old_imgs.split(',') if img and img not in deleted_files]
        if saved or final_old_imgs:
            image_path = ','.join(final_old_imgs + saved)
        else:
            image_path = ''
    finally:
        db_tmp.close()

    db = get_db()
    try:
        if image_path:
            db.execute("""UPDATE tbm_logs SET work_details_hazards=?, safety_measures=?,
                          special_notes=?, created_date=?, updated_at=?, image_path=? WHERE id=?""",
                       (request.form.get('work_details_hazards',''), request.form.get('safety_measures',''),
                        request.form.get('special_notes',''), request.form.get('created_date',''), now_iso(), image_path, tid))
        else:
            db.execute("""UPDATE tbm_logs SET work_details_hazards=?, safety_measures=?,
                          special_notes=?, created_date=?, updated_at=? WHERE id=?""",
                       (request.form.get('work_details_hazards',''), request.form.get('safety_measures',''),
                        request.form.get('special_notes',''), request.form.get('created_date',''), now_iso(), tid))
        db.commit()
        log = row_to_dict(db.execute("SELECT * FROM tbm_logs WHERE id=?", (tid,)).fetchone())
        return jsonify({'success': True, 'tbm_log': log})
    except Exception as e:
        print(f'[Error in upload]: {e}')
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

@app.route('/api/tbm/<tid>', methods=['DELETE'])
def simple_delete_tbm(tid):
    user_id = get_current_user_id()
    user = get_user(user_id)
    db = get_db()
    try:
        db.execute("DELETE FROM tbm_logs WHERE id=?", (tid,))
        db.commit()
        return jsonify({'success': True})
    finally:
        db.close()


# ════════════════════════════════════════════════════════════
# 11. 단순화 작업계획서 API  /api/workplans
# ════════════════════════════════════════════════════════════
@app.route('/api/workplans', methods=['GET'])
def simple_get_workplans():
    user_id = get_current_user_id()
    view_as = request.args.get('viewAsUserId', '').strip()
    u = get_user(user_id)
    if u and u.get('role') == 'admin' and view_as:
        user_id = view_as
    project_id = request.args.get('projectId', 'all')
    db = get_db()
    try:
        assigned = get_user_assigned_project_ids(user_id) if user_id else None
        sql = "SELECT * FROM workplans WHERE project_id IN (SELECT id FROM projects WHERE status != 'completed')"
        params = []
        if assigned is not None:
            if project_id and project_id != 'all':
                if project_id not in assigned:
                    sql += " AND 1=0"
                else:
                    sql += " AND project_id=?"
                    params.append(project_id)
            else:
                if len(assigned) == 0:
                    sql += " AND 1=0"
                else:
                    placeholders = ','.join('?' * len(assigned))
                    sql += f" AND project_id IN ({placeholders})"
                    params.extend(assigned)
        else:
            if project_id and project_id != 'all':
                sql += " AND project_id=?"
                params.append(project_id)
        sql += " ORDER BY created_at DESC"
        plans = rows_to_list(db.execute(sql, params).fetchall())
        return jsonify({'success': True, 'work_plans': plans})
    finally:
        db.close()

@app.route('/api/workplans', methods=['POST'])
def simple_create_workplan():
    user = get_user(get_current_user_id())
    active_id = request.form.get('projectId') or get_active_project_id() or ''
    
    image_path = ''
    files = request.files.getlist('files')
    if not files:
        f = request.files.get('file')
        if f and f.filename: files = [f]
    saved = []
    for f in files:
        if f and f.filename and allowed_file(f.filename):
            ext = (os.path.splitext(f.filename)[1] or '').lower()
            unique_name = f"wp_{new_id('img')}{ext}"
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_name)
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            f.save(save_path)
            
            if ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif']:
                try:
                    img = Image.open(save_path)
                    img.thumbnail((1200, 1200))
                    img.save(save_path, optimize=True, quality=85)
                except Exception:
                    pass
            saved.append(unique_name)
    if saved:
        image_path = ','.join(saved)

    db = get_db()
    try:
        wid = new_id('wp')
        n = now_iso()
        
        # image_path 컬럼 추가 반영
        cols = {row[1] for row in db.execute("PRAGMA table_info(workplans)").fetchall()}
        if 'image_path' not in cols:
            db.execute("ALTER TABLE workplans ADD COLUMN image_path TEXT DEFAULT ''")
            db.commit()

        db.execute(
            "INSERT INTO workplans (id, project_id, work_date, work_content, manager_name, creator_id, created_at, image_path) VALUES (?,?,?,?,?,?,?,?)",
            (wid, active_id,
             request.form.get('work_date', n[:10]),
             request.form.get('work_content',''),
             request.form.get('manager_name',''),
             user['id'] if user else '', n, image_path)
        )
        db.commit()
        plan = row_to_dict(db.execute("SELECT * FROM workplans WHERE id=?", (wid,)).fetchone())
        if user:
            add_audit_log(user['id'], user['name'], user['role'], 'EDIT', f"작업계획서 작성: {request.form.get('work_date','')}")
        return jsonify({'success': True, 'work_plan': plan})
    finally:
        db.close()

@app.route('/api/workplans/<wid>', methods=['GET'])
def simple_get_workplan_one(wid):
    db = get_db()
    try:
        plan = row_to_dict(db.execute("SELECT * FROM workplans WHERE id=?", (wid,)).fetchone())
        return jsonify({'success': True, 'work_plan': plan})
    finally:
        db.close()

@app.route('/api/workplans/<wid>', methods=['PUT'])
def simple_update_workplan(wid):
    image_path = None
    files = request.files.getlist('files')
    if not files:
        f = request.files.get('file')
        if f and f.filename: files = [f]
    saved = []
    for f in files:
        if f and f.filename and allowed_file(f.filename):
            ext = (os.path.splitext(f.filename)[1] or '').lower()
            unique_name = f"wp_{new_id('img')}{ext}"
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_name)
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            f.save(save_path)
            
            if ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif']:
                try:
                    img = Image.open(save_path)
                    img.thumbnail((1200, 1200))
                    img.save(save_path, optimize=True, quality=85)
                except Exception:
                    pass
            saved.append(unique_name)
    if saved:
        db_tmp = get_db()
        try:
            old = row_to_dict(db_tmp.execute("SELECT image_path FROM workplans WHERE id=?", (wid,)).fetchone())
            old_imgs = (old or {}).get('image_path', '')
            if old_imgs:
                image_path = old_imgs + ',' + ','.join(saved)
            else:
                image_path = ','.join(saved)
        finally:
            db_tmp.close()

    db = get_db()
    try:
        if image_path:
            db.execute("UPDATE workplans SET work_date=?, work_content=?, manager_name=?, image_path=? WHERE id=?",
                       (request.form.get('work_date',''), request.form.get('work_content',''),
                        request.form.get('manager_name',''), image_path, wid))
        else:
            db.execute("UPDATE workplans SET work_date=?, work_content=?, manager_name=? WHERE id=?",
                       (request.form.get('work_date',''), request.form.get('work_content',''),
                        request.form.get('manager_name',''), wid))
        db.commit()
        plan = row_to_dict(db.execute("SELECT * FROM workplans WHERE id=?", (wid,)).fetchone())
        return jsonify({'success': True, 'work_plan': plan})
    finally:
        db.close()

@app.route('/api/workplans/<wid>', methods=['DELETE'])
def simple_delete_workplan(wid):
    db = get_db()
    try:
        db.execute("DELETE FROM workplans WHERE id=?", (wid,))
        db.commit()
        return jsonify({'success': True})
    finally:
        db.close()


# ════════════════════════════════════════════════════════════
# 12. 공사정보 단순 API  /api/projects  (NEW 스키마)
# ════════════════════════════════════════════════════════════
@app.route('/api/projects', methods=['GET'])
def get_projects_simple():
    db = get_db()
    try:
        projects = rows_to_list(db.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall())
        user_id = get_current_user_id()
        view_as = request.args.get('viewAsUserId', '').strip()
        user = get_user(user_id) if user_id else None
        
        # [관리자 뷰 모드]
        if user and user.get('role') == 'admin' and view_as:
            user = get_user(view_as)

        if user and user.get('role') != 'admin':
            assigned = get_user_assigned_project_ids(user['id'])
            if assigned is not None:
                projects = [p for p in projects if p['id'] in assigned and p.get('status', 'active') != 'completed']
        return jsonify({'success': True, 'projects': projects})
    finally:
        db.close()

@app.route('/api/projects', methods=['POST'])
def create_project_simple():
    data = request.get_json() or {}
    user = get_user(get_current_user_id())
    name = (data.get('project_name') or '').strip()
    if not name:
        return jsonify({'error': '공사명을 입력해주세요.'}), 400
    db = get_db()
    try:
        pid = new_id('proj')
        n = now_iso()
        start = data.get('start_date','')
        end = data.get('end_date','')
        
        # [영구 고정] 공사금액 필수 해제: 비어있거나 null이면 '0'으로 안전하게 DB 저장되도록 예외 처리
        contract_amt = data.get('contract_amount', '')
        if not contract_amt:
            contract_amt = '0'
        db.execute(
            """INSERT INTO projects (id,project_name,contract_amount,start_date,end_date,
               period_text,client_name,contractor_name,location,description,extra_notes,
               site_manager,safety_manager,updated_at,updated_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (pid, name, contract_amt, start, end,
             f"{start} ~ {end}",
             '', data.get('contractor_name',''),
             data.get('location',''), data.get('description',''),
             data.get('extra_notes',''),
             data.get('site_manager',''), '',
             n, user['name'] if user else '')
        )

        db.commit()
        set_active_project_id(pid)
        
        # [자동 권한 배정] 직원이 공사를 생성한 경우, 해당 직원에게 생성된 공사 권한을 즉시 부여
        if user and user.get('role') != 'admin':
            usa_id = new_id('usa')
            db.execute(
                "INSERT INTO user_site_assignments (id, user_id, project_id, assigned_by, assigned_at) VALUES (?, ?, ?, ?, ?)",
                (usa_id, user['id'], pid, user['name'], n)
            )
            db.commit()

        proj = row_to_dict(db.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone())
        if user:
            add_audit_log(user['id'], user['name'], user['role'], 'UPLOAD', f"공사 등록: {name}")
        return jsonify({'success': True, 'project': proj})
    finally:
        db.close()

@app.route('/api/projects/<pid>', methods=['PUT'])
def update_project_simple(pid):
    data = request.get_json() or {}
    user = get_user(get_current_user_id())
    db = get_db()
    try:
        existing = row_to_dict(db.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone())
        if not existing:
            return jsonify({'error': '공사를 찾을 수 없습니다.'}), 404
        def v(k): return data.get(k) if data.get(k) is not None else existing.get(k,'')
        start = v('start_date'); end = v('end_date')
        
        # [영구 고정] 공사금액 필수 해제: 비어있거나 null이면 '0'으로 안전하게 DB 저장되도록 예외 처리
        contract_amt = v('contract_amount')
        if not contract_amt:
            contract_amt = '0'
        db.execute("""UPDATE projects SET project_name=?,contract_amount=?,start_date=?,end_date=?,
                      period_text=?,contractor_name=?,location=?,description=?,extra_notes=?,
                      site_manager=?,updated_at=?,updated_by=? WHERE id=?""",
                   (v('project_name'), contract_amt, start, end,
                    f"{start} ~ {end}",
                    v('contractor_name'), v('location'), v('description'), v('extra_notes'),
                    v('site_manager'), now_iso(),
                    user['name'] if user else '', pid))
        db.commit()
        proj = row_to_dict(db.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone())
        return jsonify({'success': True, 'project': proj})
    finally:
        db.close()

@app.route('/api/projects/<pid>/status', methods=['PATCH'])
def update_project_status(pid):
    data = request.get_json() or {}
    user = get_user(get_current_user_id())
    new_status = data.get('status')
    if not new_status in ['active', 'completed']:
        return jsonify({'error': '유효하지 않은 상태입니다.'}), 400
    
    db = get_db()
    try:
        existing = row_to_dict(db.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone())
        if not existing:
            return jsonify({'error': '공사를 찾을 수 없습니다.'}), 404
            
        # 권한 체크: 관리자이거나, 해당 현장 담당자인 경우
        if not (user and (user.get('role') == 'admin' or existing.get('creator_id') == user.get('id') or existing.get('updated_by') == user.get('name'))):
            return jsonify({'error': '상태 변경 권한이 없습니다.'}), 403
            
        db.execute("UPDATE projects SET status=?, updated_at=?, updated_by=? WHERE id=?",
                   (new_status, now_iso(), user['name'] if user else '', pid))
        db.commit()
        
        proj = row_to_dict(db.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone())
        return jsonify({'success': True, 'project': proj})
    finally:
        db.close()


@app.route('/api/projects/<pid>', methods=['DELETE'])
def delete_project_simple(pid):
    user_id = get_current_user_id()
    user = get_user(user_id)
    db = get_db()
    try:
        db.execute("DELETE FROM projects WHERE id=?", (pid,))
        db.commit()
        return jsonify({'success': True})
    finally:
        db.close()


# ════════════════════════════════════════════════════════════
# 13. 공지사항 API  /api/notices
# ════════════════════════════════════════════════════════════
@app.route('/api/notices', methods=['GET'])
def get_notices():
    db = get_db()
    try:
        notices = rows_to_list(db.execute("SELECT * FROM notices ORDER BY created_at DESC").fetchall())
        return jsonify({'success': True, 'notices': notices})
    finally:
        db.close()

@app.route('/api/notices', methods=['POST'])
def create_notice():
    user = get_user(get_current_user_id())
    if not user or user.get('role') != 'admin':
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403
    title = request.form.get('title','').strip()
    content = request.form.get('content','').strip()
    if not title:
        return jsonify({'error': '제목을 입력하세요.'}), 400
    db = get_db()
    try:
        nid = new_id('ntc')
        n = now_iso()
        file_name = ''; file_path = ''
        if 'file' in request.files:
            f = request.files['file']
            if f and f.filename:
                safe = secure_filename(f.filename)
                unique = f"{nid}_{safe}"
                save_p = os.path.join(app.config['UPLOAD_FOLDER'], unique)
                f.save(save_p)
                file_name = f.filename
                file_path = unique
        db.execute(
            "INSERT INTO notices VALUES (?,?,?,?,?,?,?,?)",
            (nid, title, content, file_name, file_path,
             user['name'], user['id'], n)
        )
        db.commit()
        notice = row_to_dict(db.execute("SELECT * FROM notices WHERE id=?", (nid,)).fetchone())
        add_audit_log(user['id'], user['name'], user['role'], 'UPLOAD', f"공지 등록: {title}")
        return jsonify({'success': True, 'notice': notice})
    finally:
        db.close()

@app.route('/api/notices/<nid>', methods=['DELETE'])
def delete_notice(nid):
    user_id = get_current_user_id()
    user = get_user(user_id)
    if not user or user.get('role') != 'admin':
        return jsonify({'error': '관리자 권한이 필요합니다.'}), 403
    db = get_db()
    try:
        notice = row_to_dict(db.execute("SELECT * FROM notices WHERE id=?", (nid,)).fetchone())
        if notice and notice.get('file_path'):
            fp = os.path.join(app.config['UPLOAD_FOLDER'], notice['file_path'])
            if os.path.exists(fp): os.remove(fp)
        db.execute("DELETE FROM notices WHERE id=?", (nid,))
        db.commit()
        return jsonify({'success': True})
    finally:
        db.close()




# ── RISK ASSESSMENTS API ──────────────────────────────────────
@app.route('/api/risk-assessments', methods=['GET'])
def get_risk_assessments():
    user_id = get_current_user_id()
    project_id = request.args.get('projectId', 'all')
    db = get_db()
    try:
        sql = "SELECT * FROM risk_assessments WHERE project_id IN (SELECT id FROM projects WHERE status != 'completed')"
        params = []
        assigned = get_user_assigned_project_ids(user_id) if user_id else None
        if assigned is not None:
            if project_id and project_id != 'all':
                if project_id not in assigned:
                    sql += " AND 1=0"
                else:
                    sql += " AND project_id=?"
                    params.append(project_id)
            else:
                if len(assigned) == 0:
                    sql += " AND 1=0"
                else:
                    placeholders = ','.join('?' * len(assigned))
                    sql += f" AND project_id IN ({placeholders})"
                    params.extend(assigned)
        else:
            if project_id and project_id != 'all':
                sql += " AND project_id=?"
                params.append(project_id)
        sql += " ORDER BY eval_date DESC"
        rows = db.execute(sql, params).fetchall()
        
        result = []
        for r in rows:
            result.append(row_to_dict(r))
        return jsonify({'success': True, 'risk_assessments': result})
    finally:
        db.close()


@app.route('/api/risk-assessments', methods=['POST'])
def create_risk_assessment():
    if request.content_type and 'multipart/form-data' in request.content_type:
        project_id = request.form.get('projectId', '')
        eval_date  = request.form.get('evalDate', '')
        task_name  = request.form.get('taskName', '')
        evaluator  = request.form.get('evaluator', '')
        content    = request.form.get('content', '')
        user_id    = request.form.get('userId', '')
    else:
        data = request.get_json() or {}
        project_id = data.get('projectId', '')
        eval_date  = data.get('evalDate', '')
        task_name  = data.get('taskName', '')
        evaluator  = data.get('evaluator', '')
        content    = data.get('content', '')
        user_id    = data.get('userId', '')
    
    file_name = ''
    file_path = ''
    
    if 'file' in request.files:
        f = request.files['file']
        if f and f.filename:
            file_name = f.filename
            safe_name = secure_filename(f.filename)
            unique_name = f"{new_id('riskimg')}_{safe_name}"
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_name)
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            f.save(save_path)
            file_path = unique_name

    rid = new_id('risk')
    n = now_iso()
    
    db = get_db()
    try:
        db.execute(
            """INSERT INTO risk_assessments
               (id, project_id, eval_date, task_name, evaluator, content, file_name, file_path, creator_id, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (rid, project_id, eval_date, task_name, evaluator, content, file_name, file_path, user_id, n)
        )
        db.commit()
        return jsonify({'success': True, 'message': '위험성평가가 등록되었습니다.', 'id': rid})
    except Exception as e:
        print(f'[Error in upload]: {e}')
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

@app.route('/api/risk-assessments/<rid>', methods=['PUT'])
def update_risk_assessment(rid):
    db = get_db()
    try:
        row = db.execute("SELECT * FROM risk_assessments WHERE id = ?", (rid,)).fetchone()
        if not row:
            return jsonify({'error': 'Not found'}), 404
            
        project_id = request.form.get('projectId', row['project_id'])
        eval_date  = request.form.get('evalDate', row['eval_date'])
        task_name  = request.form.get('taskName', row['task_name'])
        evaluator  = request.form.get('evaluator', row['evaluator'])
        content    = request.form.get('content', row['content'])
        
        current_file_path = row['file_path'] or ''
        current_file_name = row['file_name'] or ''
        
        deleted_files = request.form.get('deleted_files', '').split(',')
        deleted_files = [f.strip() for f in deleted_files if f.strip()]
        
        if current_file_path and current_file_path in deleted_files:
            try:
                os.remove(os.path.join(app.config['UPLOAD_FOLDER'], current_file_path))
            except:
                pass
            current_file_path = ''
            current_file_name = ''
            
        if 'file' in request.files:
            f = request.files['file']
            if f and f.filename:
                if current_file_path:
                    try:
                        os.remove(os.path.join(app.config['UPLOAD_FOLDER'], current_file_path))
                    except:
                        pass
                current_file_name = f.filename
                safe_name = secure_filename(f.filename)
                unique_name = f"{new_id('riskimg')}_{safe_name}"
                save_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_name)
                os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
                f.save(save_path)
                current_file_path = unique_name
                
        db.execute("""
            UPDATE risk_assessments 
            SET project_id=?, eval_date=?, task_name=?, evaluator=?, content=?, file_path=?, file_name=?
            WHERE id=?
        """, (project_id, eval_date, task_name, evaluator, content, current_file_path, current_file_name, rid))
        db.commit()
        
        return jsonify({'success': True, 'message': '위험성평가가 수정되었습니다.'})
    except Exception as e:
        print(f'[Error updating risk assessment]: {e}')
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()


@app.route('/api/risk-assessments/<rid>', methods=['DELETE'])
def delete_risk_assessment(rid):
    db = get_db()
    try:
        db.execute("DELETE FROM risk_assessments WHERE id=?", (rid,))
        db.commit()
        return jsonify({'success': True, 'message': '삭제되었습니다.'})
    finally:
        db.close()


# ════════════════════════════════════════════════════════════
# 16. 작업일보 API  /api/daily-reports
# ════════════════════════════════════════════════════════════
@app.route('/api/daily-reports', methods=['GET'])
def get_daily_reports():
    user_id = get_current_user_id()
    view_as = request.args.get('viewAsUserId', '').strip()
    u = get_user(user_id)
    if u and u.get('role') == 'admin' and view_as:
        user_id = view_as
    project_id = request.args.get('projectId', 'all')
    db = get_db()
    try:
        assigned = get_user_assigned_project_ids(user_id) if user_id else []
        sql = "SELECT * FROM daily_reports WHERE project_id IN (SELECT id FROM projects WHERE status != 'completed')"
        params = []
        if assigned is not None:
            if project_id and project_id != 'all':
                if project_id not in assigned:
                    sql += " AND 1=0"
                else:
                    sql += " AND project_id=?"
                    params.append(project_id)
            else:
                if len(assigned) == 0:
                    sql += " AND 1=0"
                else:
                    placeholders = ','.join('?' * len(assigned))
                    sql += f" AND project_id IN ({placeholders})"
                    params.extend(assigned)
        else:
            if project_id and project_id != 'all':
                sql += " AND project_id=?"
                params.append(project_id)
        sql += " ORDER BY created_at DESC"
        reports = rows_to_list(db.execute(sql, params).fetchall())
        return jsonify({'success': True, 'daily_reports': reports})
    finally:
        db.close()

@app.route('/api/daily-reports', methods=['POST'])
def create_daily_report():
    user = get_user(get_current_user_id())
    active_id = request.form.get('projectId') or get_active_project_id() or ''
    
    image_path = ''
    files = request.files.getlist('files')
    if not files:
        f = request.files.get('file')
        if f and f.filename: files = [f]
    saved = []
    for f in files:
        if f and f.filename and allowed_file(f.filename):
            ext = (os.path.splitext(f.filename)[1] or '').lower()
            unique_name = f"dr_{new_id('img')}{ext}"
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_name)
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            f.save(save_path)
            
            if ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif']:
                try:
                    img = Image.open(save_path)
                    img.thumbnail((1200, 1200))
                    img.save(save_path, optimize=True, quality=85)
                except Exception:
                    pass
            saved.append(unique_name)
    if saved: image_path = ','.join(saved)
    
    did = new_id('dr')
    n = now_iso()
    db = get_db()
    try:
        db.execute(
            """INSERT INTO daily_reports 
                 (id, project_id, work_date, work_content, manager_name, creator_id, created_at, image_path)
                 VALUES (?,?,?,?,?,?,?,?)""",
            (did, request.form.get('projectId') or active_id,
             request.form.get('work_date',''), request.form.get('work_content',''),
             request.form.get('manager_name',''), user['id'] if user else '', n, image_path)
        )
        db.commit()
        report = row_to_dict(db.execute("SELECT * FROM daily_reports WHERE id=?", (did,)).fetchone())
        return jsonify({'success': True, 'daily_report': report})
    except Exception as e:
        print(f'[Error in upload]: {e}')
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

@app.route('/api/daily-reports/<did>', methods=['PUT'])
def update_daily_report(did):
    user = get_user(get_current_user_id())
    
    image_path = ''
    files = request.files.getlist('files')
    if not files:
        f = request.files.get('file')
        if f and f.filename: files = [f]
    saved = []
    for f in files:
        if f and f.filename and allowed_file(f.filename):
            ext = (os.path.splitext(f.filename)[1] or '').lower()
            unique_name = f"dr_{new_id('img')}{ext}"
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_name)
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            f.save(save_path)
            
            if ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif']:
                try:
                    img = Image.open(save_path)
                    img.thumbnail((1200, 1200))
                    img.save(save_path, optimize=True, quality=85)
                except Exception:
                    pass
            saved.append(unique_name)
    if saved:
        db_tmp = get_db()
        try:
            old = row_to_dict(db_tmp.execute("SELECT image_path FROM daily_reports WHERE id=?", (did,)).fetchone())
            old_imgs = (old or {}).get('image_path', '')
            if old_imgs:
                image_path = old_imgs + ',' + ','.join(saved)
            else:
                image_path = ','.join(saved)
        finally:
            db_tmp.close()

    db = get_db()
    try:
        if image_path:
            db.execute("""UPDATE daily_reports SET work_date=?, work_content=?, manager_name=?, image_path=? WHERE id=?""",
                       (request.form.get('work_date',''), request.form.get('work_content',''),
                        request.form.get('manager_name',''), image_path, did))
        else:
            db.execute("""UPDATE daily_reports SET work_date=?, work_content=?, manager_name=? WHERE id=?""",
                       (request.form.get('work_date',''), request.form.get('work_content',''),
                        request.form.get('manager_name',''), did))
        db.commit()
        report = row_to_dict(db.execute("SELECT * FROM daily_reports WHERE id=?", (did,)).fetchone())
        return jsonify({'success': True, 'daily_report': report})
    except Exception as e:
        print(f'[Error in upload]: {e}')
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

@app.route('/api/daily-reports/<did>', methods=['DELETE'])
def delete_daily_report(did):
    db = get_db()
    try:
        db.execute("DELETE FROM daily_reports WHERE id=?", (did,))
        db.commit()
        return jsonify({'success': True})
    finally:
        db.close()

# ── 앱 시작 ─────────────────────────────────────────────────

if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8', errors='replace') if hasattr(sys.stdout, 'reconfigure') else None
    print("=" * 60)
    print("  Smart DMS - Document Management System (Python Flask)")
    print("=" * 60)
    init_db()
    print(">> Server started: http://localhost:5000")
    print("   Stop: Ctrl+C")
    print("=" * 60)
    port = int(os.environ.get('PORT', 5000))
    app.config['TEMPLATES_AUTO_RELOAD'] = True
    app.run(host='0.0.0.0', port=port, debug=True)
