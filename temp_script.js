
    // 테마 초기화
    if (localStorage.getItem('theme') === 'light') {
      document.documentElement.classList.add('light-theme');
    }
    document.addEventListener("DOMContentLoaded", () => {
      const btn = document.getElementById('theme-toggle-btn');
      if (btn) btn.innerHTML = document.documentElement.classList.contains('light-theme') ? '🌙 어두운 테마' : '☀️ 밝은 테마';
    });

    function toggleTheme() {
      const isLight = document.documentElement.classList.toggle('light-theme');
      localStorage.setItem('theme', isLight ? 'light' : 'dark');
      const btn = document.getElementById('theme-toggle-btn');
      if (btn) btn.innerHTML = isLight ? '🌙 어두운 테마' : '☀️ 밝은 테마';
    }

    const apiBase = '';

    'use strict';

    // ── State ──────────────────────────────────────────────
    let currentUser = null;
    let navHistory = [];
    let navIndex = -1;
    let editingWorkerId = null;
    let editingTbmId = null;
    let editingWpId = null;
    let allDocs = [];

    // ── Helpers ─────────────────────────────────────────────
    function esc(s) { return (s || '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
    function fmtDate(s) { return (s || '').replace('T', ' ').slice(0, 16); }
    function fmtAuthor(name) {
      if (!name) return '-';
      if (name.includes('관리자 계정') || name.includes('안전관리팀') || name === '김관리 팀장' || name === 'safety') return '관리자';
      return esc(name);
    }

    function openLightbox(src) {
      const overlay = document.getElementById('lightbox-overlay');
      document.getElementById('lightbox-img').src = src;
      document.getElementById('lightbox-download').href = src + '/download';
      overlay.style.display = 'flex';
    }
    function closeLightbox() {
      document.getElementById('lightbox-overlay').style.display = 'none';
    }

    async function api(url, opts = {}) {
      const res = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...opts });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || '오류가 발생했습니다.');
      return data;
    }

    // ── Toast ────────────────────────────────────────────────
    function toast(msg, type = 'info', dur = 3000) {
      const icons = { success: '✅', error: '❌', info: 'ℹ️' };
      const el = document.createElement('div');
      el.className = `toast ${type}`;
      el.innerHTML = `<span>${icons[type] || '📢'}</span><span>${esc(msg)}</span>`;
      document.getElementById('toast-container').appendChild(el);
      setTimeout(() => el.remove(), dur);
    }

    // ── Modal ─────────────────────────────────────────────────
    function openModal(id) { document.getElementById(id).classList.add('active'); }
    function closeModal(id) { document.getElementById(id).classList.remove('active'); }
    function confirm2(title, msg, onOk, okLabel, btnStyle) {
      document.getElementById('confirm-title').textContent = title;
      document.getElementById('confirm-msg').textContent = msg;
      const btn = document.getElementById('confirm-ok-btn');
      btn.textContent = okLabel || '확인';
      btn.className = 'btn ' + (btnStyle || 'btn-danger');
      btn.onclick = () => { closeModal('modal-confirm'); onOk(); };
      openModal('modal-confirm');
    }

    // ── Navigation ───────────────────────────────────────────
    function navigateTo(page, push = true) {
      // 페이지 전환
      document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
      document.querySelectorAll('.sidebar-item').forEach(i => i.classList.remove('active'));
      const pageEl = document.getElementById(`page-${page}`);
      const navEl = document.getElementById(`nav-${page}`);
      if (pageEl) pageEl.classList.add('active');
      if (navEl) navEl.classList.add('active');
      // 타이틀
      const titles = { dashboard: '대시보드', project: '공사정보 관리', workers: '근로자 이력정보', workplan: '작업계획서', tbm: 'TBM 일지', risk: '위험성평가', docs: '문서 관리', auditlog: '감사 로그', accounts: '계정 관리', notice: '공지' };
      document.getElementById('topbar-title').textContent = titles[page] || page;
      // 히스토리
      if (push) { navHistory = navHistory.slice(0, navIndex + 1); navHistory.push(page); navIndex = navHistory.length - 1; }
      // 데이터 로드
      const loaders = { dashboard: loadDashboard, project: loadProjectInfo, 'completed-projects': loadProjectInfo, workers: loadWorkers, workplan: loadWorkplans, daily: loadDailyReports, tbm: loadTbmList, risk: loadRiskAssessments, docs: loadDocs, auditlog: loadAuditLog, accounts: loadAccountsPending, notice: loadNotices };
      if (loaders[page]) loaders[page]();
      // 계정 관리는 관리자만
      if (page === 'accounts' && currentUser?.role !== 'admin') { toast('관리자만 접근 가능합니다.', 'error'); navigateTo('dashboard'); }
    }
    function historyBack() { if (navIndex > 0) navigateTo(navHistory[--navIndex], false); }
    function historyFwd() { if (navIndex < navHistory.length - 1) navigateTo(navHistory[++navIndex], false); }

    // ── Auth ─────────────────────────────────────────────────
    function switchLoginTab(tab) {
      ['admin', 'empl'].forEach(t => {
        document.getElementById(`tab-${t}`).classList.toggle('active', t === tab);
        document.getElementById(`panel-${t}`).classList.toggle('active', t === tab);
      });
    }

    async function doLogin(type) {
      try {
        let body;
        if (type === 'admin') {
          body = { type: 'admin', login_id: document.getElementById('admin-id').value.trim(), password: document.getElementById('admin-pw').value };
        } else {
          body = { type: 'employee', name: document.getElementById('empl-name').value.trim(), department: document.getElementById('empl-dept').value.trim(), password: document.getElementById('empl-pw').value };
        }
        const data = await api('/api/auth/login', { method: 'POST', body: JSON.stringify(body) });
        currentUser = data.user;
        document.getElementById('login-screen').style.display = 'none';
        document.getElementById('app').style.display = 'block';
        
        // 계정 이름 중복 표기 방지
        let displayName = currentUser.name;
        if (currentUser.role === 'admin' && !displayName.includes('안전관리팀')) displayName += ' (안전관리팀)';
        else if (currentUser.role !== 'admin' && !displayName.includes('직원')) displayName += ' (직원)';
        document.getElementById('sidebar-username').textContent = displayName;
        
        const isAdmin = currentUser.role === 'admin';
        // 관리자만 노출: 계정 관리, 감사 로그
        document.getElementById('nav-accounts').style.display = isAdmin ? '' : 'none';
        document.getElementById('nav-auditlog').style.display = isAdmin ? '' : 'none';
        // 관리자: 직원별 보기 필터 활성화
        const filterEl = document.getElementById('admin-view-filter');
        if (isAdmin) {
          filterEl.style.display = 'flex';
          loadEmployeeFilter();
          loadPendingBadge();
        } else {
          filterEl.style.display = 'none';
        }
        await loadProjectDropdowns();
        navigateTo('dashboard');
        toast(`${currentUser.name}님 환영합니다!`, 'success');
      } catch (e) { toast(e.message, 'error'); }
    }

    function doLogout() {
      currentUser = null;
      document.getElementById('app').style.display = 'none';
      document.getElementById('login-screen').style.display = 'flex';
      document.getElementById('admin-pw').value = '';
      document.getElementById('empl-pw').value = '';
      navHistory = []; navIndex = -1;
    }

    // 계정 신청
    function openRegisterModal() { openModal('modal-register'); }
    async function submitRegister() {
      const name = document.getElementById('reg-name').value.trim();
      const dept = document.getElementById('reg-dept').value.trim();
      const team = document.getElementById('reg-team').value.trim();
      const pw = document.getElementById('reg-pw').value || '0000';
      if (!name || !dept) { toast('이름과 부서는 필수입니다.', 'error'); return; }
      try {
        const data = await api('/api/auth/register', { method: 'POST', body: JSON.stringify({ name, department: dept, team, password: pw }) });
        toast(data.message, 'success');
        closeModal('modal-register');
        ['reg-name', 'reg-dept', 'reg-team', 'reg-pw'].forEach(id => document.getElementById(id).value = '');
      } catch (e) { toast(e.message, 'error'); }
    }

    // ── Pending Badge ─────────────────────────────────────────
    async function loadPendingBadge() {
      try {
        const data = await api(`/api/auth/pending?userId=${currentUser?.id || ''}`);
        const cnt = (data.pending || []).filter(p => p.status === 'pending').length;
        const badge = document.getElementById('pending-badge');
        badge.textContent = cnt;
        badge.style.display = cnt > 0 ? 'inline' : 'none';
      } catch (e) { }
    }

    // ── Accounts Management ───────────────────────────────────
    function switchAccTab(tab) {
      ['pending', 'employees', 'trash'].forEach(t => {
        const panel = document.getElementById(`acc-panel-${t}`);
        if (panel) panel.style.display = t === tab ? 'block' : 'none';
        const btn = document.getElementById(`acc-tab-${t}`);
        if (btn) { btn.style.borderColor = t === tab ? 'var(--amber)' : ''; btn.style.color = t === tab ? 'var(--amber)' : ''; }
      });
      if (tab === 'employees') loadEmployeeList();
      if (tab === 'pending') loadAccountsPending();
      if (tab === 'trash') loadTrashList();
    }

    async function loadAccountsPending() {
      try {
        const data = await api(`/api/auth/pending?userId=${currentUser?.id || ''}`);
        const tbody = document.getElementById('pending-tbody');
        const list = (data.pending || []).filter(p => p.status === 'pending');
        if (!list.length) { tbody.innerHTML = `<tr><td colspan="8"><div class="empty-state"><div class="empty-icon">📭</div><p>신청 내역이 없습니다.</p></div></td></tr>`; return; }
        tbody.innerHTML = list.map((p, idx) => {
          const statusBadge = p.status === 'pending' ? `<span class="badge badge-amber">⏳ 대기중</span>` : p.status === 'approved' ? `<span class="badge badge-green">✅ 승인</span>` : `<span class="badge badge-red">❌ 거절</span>`;
          const actions = `
        <div class="td-actions">
          <button class="btn btn-sm" style="background:rgba(16,185,129,.2);border:1px solid #10b981;color:#10b981;" onclick="approveUser('${p.id}','${esc(p.name)}')">✅ 승인</button>
          <button class="btn btn-sm" style="background:rgba(245,158,11,.2);border:1px solid #f59e0b;color:#f59e0b;" onclick="suspendPendingUser('${p.id}','${esc(p.name)}')">⏸ 미사용</button>
          <button class="btn btn-sm" style="background:rgba(239,68,68,.2);border:1px solid #ef4444;color:#ef4444;" onclick="rejectUser('${p.id}','${esc(p.name)}')">🗑️ 거절</button>
        </div>`;
          return `<tr>
        <td style="text-align:center;">${idx + 1}</td>
        <td class="fw-600">${esc(p.name)}</td>
        <td class="td-muted">${esc(p.department)}</td>
        <td class="td-muted">${esc(p.team) || '-'}</td>
        <td>${statusBadge}</td>
        <td class="td-muted">${fmtDate(p.created_at)}</td>
        <td class="td-muted">${esc(p.reviewed_by) || '-'}</td>
        <td>${actions}</td>
      </tr>`;
        }).join('');
      } catch (e) { toast('목록 로딩 실패: ' + e.message, 'error'); }
    }

    async function approveUser(pid, name) {
      confirm2('계정 승인', `"${name}" 계정을 승인하시겠습니까?`, async () => {
        try {
          const data = await api(`/api/auth/approve/${pid}`, { method: 'POST', body: JSON.stringify({ adminUserId: currentUser?.id }) });
          toast(data.message, 'success');
          loadAccountsPending(); loadPendingBadge();
          switchAccTab('employees');
        } catch (e) { toast(e.message, 'error'); }
      }, '✅ 승인 확인', 'btn-primary');
    }

    async function suspendPendingUser(pid, name) {
      confirm2('미사용 처리', `"${name}" 계정을 미사용 상태로 처리하시겠습니까?\n(로그인은 불가하지만 언제든 활성화 가능합니다.)`, async () => {
        try {
          const data = await api(`/api/auth/suspend-pending/${pid}`, { method: 'POST', body: JSON.stringify({ adminUserId: currentUser?.id }) });
          toast(data.message, 'success');
          loadAccountsPending(); loadPendingBadge();
        } catch (e) { toast(e.message, 'error'); }
      }, '⏸ 미사용 확인', 'btn-secondary');
    }

    async function rejectUser(pid, name) {
      confirm2('계정 신청 삭제', `"${name}" 계정 신청을 삭제하시겠습니까?`, async () => {
        try {
          const data = await api(`/api/auth/reject/${pid}`, { method: 'POST', body: JSON.stringify({ adminUserId: currentUser?.id }) });
          toast(data.message, 'success');
          loadAccountsPending(); loadPendingBadge();
        } catch (e) { toast(e.message, 'error'); }
      }, '🗑️ 삭제 확인', 'btn-danger');
    }

    async function loadEmployeeList() {
      try {
        const data = await api(`/api/auth/employees?userId=${currentUser?.id || ''}`);
        const tbody = document.getElementById('employees-tbody');
        const list = data.employees || [];
        if (!list.length) { tbody.innerHTML = `<tr><td colspan="8"><div class="empty-state"><div class="empty-icon">👥</div><p>등록된 직원이 없습니다.</p></div></td></tr>`; return; }
        const activeList = list.filter(e => e.status !== 'deleted');
        tbody.innerHTML = activeList.map((e, idx) => {
          const badge = e.status === 'active' ? `<span class="badge badge-green">✅ 활성</span>` : `<span class="badge badge-amber">⏸ 미사용</span>`;
          const toggleLabel = e.status === 'suspended' ? '✅ 활성화' : '⏸ 미사용';
          return `<tr>
        <td style="text-align:center;"><input type="checkbox" class="emp-checkbox" value="${e.id}" style="margin-right:4px;"> ${idx + 1}</td>
        <td class="fw-600">${esc(e.name)}</td>
        <td class="td-muted">${esc(e.department) || '-'}</td>
        <td class="td-muted">${esc(e.team) || '-'}</td>
        <td>${badge}</td>
        <td class="td-muted">${fmtDate(e.created_at)}</td>
        <td><div class="td-actions">
          <button class="btn btn-sm" style="background:rgba(245,158,11,.15);border:1px solid #f59e0b;color:#f59e0b;" onclick="toggleUserStatus('${e.id}','${esc(e.name)}','${e.status}')">${toggleLabel}</button>
          <button class="btn btn-sm" style="background:rgba(99,102,241,.15);border:1px solid #6366f1;color:#6366f1;" onclick="resetUserPw('${e.id}','${esc(e.name)}')">🔑 초기화</button>
          
        </div></td>
      </tr>`;
        }).join('');
      } catch (e) { toast('직원 목록 로딩 실패: ' + e.message, 'error'); }
    }

    async function toggleUserStatus(uid, name, currentStatus) {
      const label = currentStatus === 'suspended' ? '활성화' : '미사용';
      confirm2(`계정 ${label}`, `"${name}" 계정을 ${label} 처리하시겠습니까?`, async () => {
        try {
          const data = await api(`/api/auth/toggle-status/${uid}`, { method: 'POST', body: JSON.stringify({ adminUserId: currentUser?.id }) });
          toast(data.message, 'success'); loadEmployeeList();
        } catch (e) { toast(e.message, 'error'); }
      }, label + ' 확인', 'btn-secondary');
    }

    async function resetUserPw(uid, name) {
      confirm2('비밀번호 초기화', `"${name}"의 비밀번호를 0000으로 초기화하시겠습니까?`, async () => {
        try {
          const data = await api(`/api/auth/reset-password/${uid}`, { method: 'POST', body: JSON.stringify({ adminUserId: currentUser?.id }) });
          toast(data.message, 'success');
        } catch (e) { toast(e.message, 'error'); }
      }, '🔑 초기화 확인', 'btn-danger');
    }

    async function deleteEmployee(uid, name) {
      confirm2('계정 삭제', `"${name}" 계정을 삭제하시겠습니까?\n(휴지통에서 복구할 수 있습니다.)`, async () => {
        try {
          const data = await api(`/api/auth/delete/${uid}`, { method: 'DELETE', body: JSON.stringify({ adminUserId: currentUser?.id }) });
          toast(data.message, 'success'); loadEmployeeList();
        } catch (e) { toast(e.message, 'error'); }
      }, '🗑️ 삭제 확인', 'btn-danger');
    }

    async function loadTrashList() {
      try {
        const data = await api(`/api/auth/deleted-employees?userId=${currentUser?.id || ''}`);
        const list = data.employees || [];
        const tbody = document.getElementById('trash-tbody');
        if (!list.length) { tbody.innerHTML = `<tr><td colspan="6"><div class="empty-state"><div class="empty-icon">🗑️</div><p>삭제된 계정이 없습니다.</p></div></td></tr>`; return; }
        tbody.innerHTML = list.map((e, idx) => `<tr>
      <td style="text-align:center;"><input type="checkbox" class="trash-checkbox" value="${e.id}" style="margin-right:4px;"> ${idx + 1}</td>
      <td class="fw-600">${esc(e.name)}</td>
      <td class="td-muted">${esc(e.department) || '-'}</td>
      <td class="td-muted">${esc(e.team) || '-'}</td>
      <td class="td-muted">${fmtDate(e.created_at)}</td>
      <td><button class="btn btn-sm" style="background:rgba(16,185,129,.2);border:1px solid #10b981;color:#10b981;" onclick="restoreEmployee('${e.id}','${esc(e.name)}')">♻️ 복구</button> <button class="btn btn-sm" style="background:rgba(239,68,68,.2);border:1px solid #ef4444;color:#ef4444;" onclick="hardDeleteEmployee('${e.id}','${esc(e.name)}')">🗑️ 영구삭제</button></td>
    </tr>`).join('');
      } catch (e) { toast('휴지통 로딩 실패: ' + e.message, 'error'); }
    }

    async function deleteSelectedEmployees() {
      const cbs = document.querySelectorAll('#employees-tbody .emp-checkbox:checked');
      if (!cbs.length) { toast('삭제할 계정을 선택하세요.', 'error'); return; }
      const ids = Array.from(cbs).map(cb => cb.value);
      confirm2('선택 삭제', `선택한 ${ids.length}개의 계정을 삭제하시겠습니까?`, async () => {
        try {
          const data = await api('/api/auth/delete-accounts', { method: 'POST', body: JSON.stringify({ userId: currentUser?.id, accountIds: ids }) });
          toast('삭제되었습니다.', 'success'); loadEmployeeList();
        } catch (e) { toast(e.message, 'error'); }
      }, '🗑️ 삭제 확인', 'btn-danger');
    }

    async function restoreSelectedEmployees() {
      const cbs = document.querySelectorAll('#trash-tbody .trash-checkbox:checked');
      if (!cbs.length) { toast('복원할 계정을 선택하세요.', 'error'); return; }
      const ids = Array.from(cbs).map(cb => cb.value);
      confirm2('선택 복원', `선택한 ${ids.length}개의 계정을 복원하시겠습니까?`, async () => {
        try {
          const data = await api('/api/auth/restore-accounts', { method: 'POST', body: JSON.stringify({ userId: currentUser?.id, accountIds: ids }) });
          toast('복원되었습니다.', 'success'); 
          switchAccTab('employees');
        } catch (e) { toast(e.message, 'error'); }
      }, '♻️ 복원 확인', 'btn-primary');
    }

    async function permanentlyDeleteSelectedEmployees() {
      const cbs = document.querySelectorAll('#trash-tbody .trash-checkbox:checked');
      if (!cbs.length) { toast('영구삭제할 계정을 선택하세요.', 'error'); return; }
      const ids = Array.from(cbs).map(cb => cb.value);
      confirm2('선택 영구삭제', `선택한 ${ids.length}개의 계정을 영구적으로 삭제하시겠습니까?\n이 작업은 되돌릴 수 없습니다.`, async () => {
        try {
          const data = await api('/api/auth/hard-delete-accounts', { method: 'POST', body: JSON.stringify({ userId: currentUser?.id, accountIds: ids }) });
          toast('영구 삭제되었습니다.', 'success'); 
          switchAccTab('trash');
        } catch (e) { toast(e.message, 'error'); }
      }, '🗑️ 영구삭제 확인', 'btn-danger');
    }

    async function hardDeleteEmployee(uid, name) {
      confirm2('계정 영구삭제', `"${name}" 계정을 영구적으로 삭제하시겠습니까?\n이 작업은 되돌릴 수 없습니다.`, async () => {
        try {
          const data = await api('/api/auth/hard-delete-accounts', { method: 'POST', body: JSON.stringify({ userId: currentUser?.id, accountIds: [uid] }) });
          toast('영구 삭제되었습니다.', 'success'); 
          switchAccTab('trash');
        } catch (e) { toast(e.message, 'error'); }
      }, '🗑️ 영구삭제 확인', 'btn-danger');
    }

    async function restoreEmployee(uid, name) {
      confirm2('계정 복구', `"${name}" 계정을 복구하시겠습니까?`, async () => {
        try {
          const data = await api('/api/auth/restore-accounts', { method: 'POST', body: JSON.stringify({ userId: currentUser?.id, accountIds: [uid] }) });
          toast('복원되었습니다.', 'success'); 
          switchAccTab('employees');
        } catch (e) { toast(e.message, 'error'); }
      }, '♻️ 복구 확인', 'btn-primary');
    }

    // ── Dashboard ─────────────────────────────────────────────
    async function loadDashboard() {
      try {
        const [statsData, noticesData, projData] = await Promise.all([
          api(`/api/stats?userId=${currentUser?.id || ''}`).catch(() => ({})),
          api('/api/notices').catch(() => ({})),
          api('/api/project-info').catch(() => ({}))
        ]);
        if (projData.projectInfo) {
          document.getElementById('proj-name-label').textContent = projData.projectInfo.project_name || '공사명 미등록';
        }
        const s = statsData.stats || {};
        document.getElementById('stat-docs').textContent = s.totalDocuments ?? '-';
        document.getElementById('stat-workers').textContent = s.workerCount ?? '-';
        document.getElementById('stat-tbm').textContent = s.tbmCount ?? '-';
        document.getElementById('stat-workplans').textContent = s.workPlanCount ?? '-';
        
        const notices = (noticesData.notices || []).slice(0, 10);
        const tbody = document.getElementById('dash-notice-tbody');
        if (!notices.length) { tbody.innerHTML = `<tr><td colspan="4"><div class="empty-state"><p>최근 등록된 글이 없습니다.</p></div></td></tr>`; return; }
        tbody.innerHTML = notices.map(n => `<tr>
      <td class="fw-600">${esc(n.title)}</td>
      <td class="td-muted">${fmtAuthor(n.author_name)}</td>
      <td class="td-muted" style="white-space:nowrap;">${fmtDate(n.created_at)}</td>
      <td>${n.file_name ? `<a href="/uploads/${encodeURIComponent(n.file_path)}" target="_blank" style="color:var(--accent);font-size:13px;">📎 다운로드</a>` : '-'}</td>
    </tr>`).join('');
      } catch (e) { }
    }

    // ── Project Info ──────────────────────────────────────────
    let projectDataList = [];
    let editingProjectId = null;

    async function loadProjectDropdowns() {
      try {
        const viewAs = document.getElementById('view-as-employee')?.value || '';
        const data = await api(`/api/project-info?userId=${currentUser?.id || ''}&viewAsUserId=${viewAs}`);
        const projects = data.projects || [];
        
        const activeProjects = projects.filter(p => p.status !== 'completed');
        const completedProjects = projects.filter(p => p.status === 'completed');
        
        const activeOpts = activeProjects.map(p => `<option value="${p.id}">${esc(p.project_name)}</option>`).join('');
        const compOpts = completedProjects.map(p => `<option value="${p.id}">${esc(p.project_name)}</option>`).join('');
        
        let options = '';
        if (activeOpts) options += `<optgroup label="진행중 현장">${activeOpts}</optgroup>`;
        if (compOpts) options += `<optgroup label="준공된 현장">${compOpts}</optgroup>`;
        
        let defaultId = '';
        if (activeProjects.length > 0) defaultId = activeProjects[0].id;
        else if (completedProjects.length > 0) defaultId = completedProjects[0].id;

        ['filter-workers-project', 'filter-workplan-project', 'filter-daily-project', 'filter-tbm-project', 'filter-risk-project'].forEach(id => {
          const el = document.getElementById(id);
          if (el) {
            const oldVal = el.value;
            el.innerHTML = options;
            
            const isValid = activeProjects.some(p => p.id === oldVal) || completedProjects.some(p => p.id === oldVal);
            if (isValid) {
                el.value = oldVal;
            } else if (defaultId) {
                el.value = defaultId;
            }
          }
        });
        
        const activeOnlyOpts = activeProjects.map(p => `<option value="${p.id}">${esc(p.project_name)}</option>`).join('');
        ['wp-project', 'daily-project', 'tbm-project', 'risk-project'].forEach(id => {
            const el = document.getElementById(id);
            if (el) {
                const oldVal = el.value;
                el.innerHTML = activeOnlyOpts;
                
                const isValid = activeProjects.some(p => p.id === oldVal);
                if (isValid) {
                    el.value = oldVal;
                } else if (activeProjects.length > 0) {
                    el.value = activeProjects[0].id;
                }
            }
        });
        
      } catch (e) { console.error('Project dropdown load failed', e); }
    }
    
    async function loadProjectInfo() {
      try {
        const viewAs = document.getElementById('view-as-employee')?.value || '';
        const data = await api(`/api/project-info?userId=${currentUser?.id || ''}&viewAsUserId=${viewAs}`);
        projectDataList = data.projects || [];
        const container = document.getElementById('proj-view');
        const isAdmin = currentUser?.role === 'admin';

        const activeProjects = projectDataList.filter(p => p.status !== 'completed');
        const completedProjects = projectDataList.filter(p => p.status === 'completed');
        
        const compContainer = document.getElementById('completed-proj-view');
        
        // Render Active Projects
        if (container) {
          if (!activeProjects.length) { container.innerHTML = '<div class="empty-state"><div class="empty-icon">🏗️</div><p>등록된 진행중 현장이 없습니다.</p></div>'; }
          else {
            container.innerHTML = activeProjects.map(p => {
          const canEdit = isAdmin || p.updated_by === currentUser?.name;
          return `
          <div style="border:1px solid var(--border);border-radius:10px;padding:16px;margin-bottom:16px;background:var(--bg-panel);">
            <div style="display:flex;justify-content:space-between;margin-bottom:12px;align-items:center;">
              <h4 style="margin:0;color:var(--text-primary);font-size:16px;">${esc(p.project_name)}</h4>
              ${canEdit ? `<div>
                <button class="btn btn-secondary btn-sm" onclick="editProject('${p.id}')">✏️ 수정</button>
                <button class="btn btn-danger btn-sm" onclick="deleteProject('${p.id}')">🗑️ 삭제</button>
              </div>` : ''}
            </div>
            <div class="grid-2" style="gap:16px;">
              <div><label style="color:var(--text-muted);font-size:12px;">업체명 / 발주처</label><p style="margin-top:4px;font-size:14px;font-weight:600;">${esc(p.contractor_name || p.client_name || '-')}</p></div>
              <div><label style="color:var(--text-muted);font-size:12px;">공사 기간</label><p style="margin-top:4px;font-size:13px;">${esc(p.start_date)} ~ ${esc(p.end_date)}</p></div>
              <div><label style="color:var(--text-muted);font-size:12px;">공사 금액</label><p style="margin-top:4px;font-size:13px;">${esc(p.contract_amount)}</p></div>
              <div><label style="color:var(--text-muted);font-size:12px;">공사담당자</label><p style="margin-top:4px;font-size:13px;">${esc(p.site_manager)}</p></div>
              <div style="grid-column:1/-1;"><label style="color:var(--text-muted);font-size:12px;">현장 주소</label><p style="margin-top:4px;font-size:13px;">${esc(p.location || p.site_address)}</p></div>
            </div>
          </div>`;
            }).join('');
          }
        }
        
        // Render Completed Projects
        if (compContainer) {
          if (!completedProjects.length) { compContainer.innerHTML = '<div class="empty-state"><div class="empty-icon">✅</div><p>준공된 현장이 없습니다.</p></div>'; }
          else {
            compContainer.innerHTML = completedProjects.map(p => {
              const canEdit = isAdmin || p.updated_by === currentUser?.name;
              return `
              <div style="border:1px solid var(--border);border-radius:10px;padding:16px;margin-bottom:16px;background:var(--bg-panel);opacity:0.8;">
                <div style="display:flex;justify-content:space-between;margin-bottom:12px;align-items:center;">
                  <h4 style="margin:0;color:var(--text-primary);font-size:16px;">${esc(p.project_name)}</h4>
                  ${canEdit ? `<div>
                    <button class="btn btn-sm" style="background:#f59e0b;color:white;border:none;" onclick="restoreProject('${p.id}')">🔄 진행중 복구</button>
                    <button class="btn btn-danger btn-sm" onclick="deleteProject('${p.id}')">🗑️ 삭제</button>
                  </div>` : ''}
                </div>
                <div class="grid-2" style="gap:16px;">
                  <div><label style="color:var(--text-muted);font-size:12px;">업체명 / 발주처</label><p style="margin-top:4px;font-size:14px;font-weight:600;">${esc(p.contractor_name || p.client_name || '-')}</p></div>
                  <div><label style="color:var(--text-muted);font-size:12px;">공사 기간</label><p style="margin-top:4px;font-size:13px;">${esc(p.start_date)} ~ ${esc(p.end_date)}</p></div>
                </div>
              </div>`;
            }).join('');
          }
        }
      } catch (e) { toast('공사정보 로딩 실패: ' + e.message, 'error'); }
    }

    // ── Workers ───────────────────────────────────────────────
    async function loadWorkers() {
      try {
        const viewAs = document.getElementById('view-as-employee')?.value || '';
        const projId = document.getElementById('filter-workers-project')?.value || 'all';
        const url = viewAs ? `/api/workers?userId=${currentUser?.id || ''}&viewAsUserId=${viewAs}&projectId=${projId}` : `/api/workers?userId=${currentUser?.id || ''}&projectId=${projId}`;
        const data = await api(url);
        const list = data.workers || [];
        const tbody = document.getElementById('workers-tbody');
        const canEdit = currentUser?.role === 'admin';
        if (!list.length) { tbody.innerHTML = `<tr><td colspan="5"><div class="empty-state"><div class="empty-icon">👷</div><p>등록된 근로자가 없습니다.</p></div></td></tr>`; return; }
        tbody.innerHTML = list.map(w => `<tr>
      <td class="fw-600">${esc(w.name)}</td>
      <td class="td-muted">${esc(w.job_type) || '-'}</td>
      <td class="td-muted">${esc(w.nationality) || '-'}</td>
      <td class="td-muted">${esc(w.hire_date) || '-'}</td>
      <td>${canEdit ? `<div class="td-actions"><button class="btn btn-secondary btn-sm" onclick="openWorkerModal('${w.id}')">✏️</button><button class="btn btn-danger btn-sm" onclick="delWorker('${w.id}','${esc(w.name)}')">🗑️</button></div>` : '-'}</td>
    </tr>`).join('');
      } catch (e) { toast('근로자 로딩 실패: ' + e.message, 'error'); }
    }
    function openWorkerModal(id) {
      editingWorkerId = id;
      document.getElementById('worker-modal-title').textContent = id ? '근로자 수정' : '근로자 추가';
      ['w-name', 'w-job', 'w-nation', 'w-hire', 'w-note'].forEach(i => { const el = document.getElementById(i); if (el) el.value = ''; });
      if (id) {
        api(`/api/workers/${id}?userId=${currentUser?.id}`).then(data => {
          const w = data.worker;
          document.getElementById('w-name').value = w.name || '';
          document.getElementById('w-job').value = w.job_type || '';
          document.getElementById('w-nation').value = w.nationality || '';
          document.getElementById('w-hire').value = w.hire_date || '';
          document.getElementById('w-note').value = w.notes || '';
        }).catch(e => toast(e.message, 'error'));
      }
      openModal('modal-worker');
    }
    async function saveWorker() {
      const body = {
        userId: currentUser?.id,
        name: document.getElementById('w-name').value.trim(),
        job_type: document.getElementById('w-job').value.trim(),
        nationality: document.getElementById('w-nation').value.trim(),
        hire_date: document.getElementById('w-hire').value,
        notes: document.getElementById('w-note').value.trim(),
      };
      if (!body.name) { toast('이름을 입력하세요.', 'error'); return; }
      try {
        const method = editingWorkerId ? 'PUT' : 'POST';
        const url = editingWorkerId ? `/api/workers/${editingWorkerId}` : '/api/workers';
        await api(url, { method, body: JSON.stringify(body) });
        toast(editingWorkerId ? '수정되었습니다.' : '등록되었습니다.', 'success');
        closeModal('modal-worker'); loadWorkers();
      } catch (e) { toast(e.message, 'error'); }
    }
    function delWorker(id, name) {
      confirm2('근로자 삭제', `"${name}" 근로자 정보를 삭제하시겠습니까?`, async () => {
        try {
          await api(`/api/workers/${id}`, { method: 'DELETE', body: JSON.stringify({ userId: currentUser?.id }) });
          toast('삭제되었습니다.', 'success'); loadWorkers();
        } catch (e) { toast(e.message, 'error'); }
      }, '🗑️ 삭제 확인', 'btn-danger');
    }

    
    // ── Daily Reports ────────────────────────────────────────────────
    let editingDailyId = null;
    async function loadDailyReports() {
      try {
        const viewAs = document.getElementById('view-as-employee')?.value || '';
        const projId = document.getElementById('filter-daily-project')?.value || 'all';
        const data = await api(`/api/daily-reports?userId=${currentUser?.id || ''}&viewAsUserId=${viewAs}&projectId=${projId}`);
        const list = data.daily_reports || [];
        const tbody = document.getElementById('daily-tbody');
        const canEdit = currentUser?.role === 'admin';
        if (!list.length) { tbody.innerHTML = `<tr><td colspan="6"><div class="empty-state"><div class="empty-icon">📰</div><p>작업일보 내역이 없습니다.</p></div></td></tr>`; return; }
        
        tbody.innerHTML = list.map(d => {
          const imgs = (d.image_path || '').split(',').filter(x => x.trim());
          return `<tr>
            <td class="fw-600">${esc(d.work_date)}</td>
            <td style="white-space:pre-wrap;">${esc(d.work_content)}</td>
            <td class="td-muted">${esc(d.manager_name)}</td>
            <td>
              <span class="badge ${d.status === '완료' ? 'badge-success' : 'badge-amber'}">${esc(d.status)}</span>
            </td>
            <td>
              ${imgs.length ? `<div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:6px;">` + imgs.map(img => `
                <div style="display:inline-flex;flex-direction:column;align-items:center;gap:2px;">
                  <img src="/uploads/${encodeURIComponent(img.trim())}" alt="사진" style="max-width:60px;max-height:50px;border-radius:6px;border:1px solid var(--border);cursor:pointer;" onclick="openLightbox('/uploads/${encodeURIComponent(img.trim())}')"/>
                  <a href="/uploads/${encodeURIComponent(img.trim())}/download" style="font-size:11px;color:var(--accent);text-decoration:none;">⬇️</a>
                </div>`).join('') + `</div>` : '-'}
            </td>
            <td>
              <div class="td-actions" style="display:inline-flex;">
                <button class="btn btn-secondary btn-sm" onclick="openDailyModal('${d.id}', '${esc(d.project_id)}', '${esc(d.work_date)}', '${esc(d.work_content)}', '${esc(d.manager_name)}', '${esc(d.status)}')">✏️</button>
                <button class="btn btn-danger btn-sm" onclick="delDailyReport('${d.id}')">🗑️</button>
              </div>
            </td>
          </tr>`;
        }).join('');
      } catch (e) { toast('작업일보 로딩 실패: ' + e.message, 'error'); }
    }
    
    function openDailyModal(id, pId, date, content, manager, status) {
      editingDailyId = id;
      document.getElementById('daily-modal-title').textContent = id ? '작업일보 수정' : '작업일보 추가';
      const sel = document.getElementById('daily-proj');
      sel.innerHTML = projectDataList.map(p => `<option value="${p.id}">${esc(p.project_name)}</option>`).join('');
      
      const today = new Date();
      const y = today.getFullYear();
      const m = String(today.getMonth() + 1).padStart(2, '0');
      const d = String(today.getDate()).padStart(2, '0');
      
      document.getElementById('daily-proj').value = pId || '';
      document.getElementById('daily-date').value = date || `${y}-${m}-${d}`;
      document.getElementById('daily-content').value = content || '';
      document.getElementById('daily-manager').value = manager || '';
      document.getElementById('daily-status').value = status || '작업중';
      document.getElementById('daily-photo').value = '';
      
      openModal('modal-daily');
    }
    
    async function saveDailyReport() {
      const projId = document.getElementById('daily-proj').value;
      const date = document.getElementById('daily-date').value;
      const content = document.getElementById('daily-content').value.trim();
      const manager = document.getElementById('daily-manager').value.trim();
      const status = document.getElementById('daily-status').value;
      
      if (!projId || !date || !content || !manager) { toast('필수 항목을 모두 입력하세요.', 'error'); return; }
      
      try {
        const fd = new FormData();
        fd.append('projectId', projId);
        fd.append('work_date', date);
        fd.append('work_content', content);
        fd.append('manager_name', manager);
        fd.append('status', status);
        fd.append('userId', currentUser?.id || '');
        
        const photoInput = document.getElementById('daily-photo');
        if (photoInput && photoInput.files) {
          for (let i = 0; i < photoInput.files.length; i++) {
            fd.append('files', photoInput.files[i]);
          }
        }
        
        const method = editingDailyId ? 'PUT' : 'POST';
        const url = editingDailyId ? `/api/daily-reports/${editingDailyId}` : '/api/daily-reports';
        
        const res = await fetch(url, { method, body: fd });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || '저장 실패');
        
        toast(editingDailyId ? '수정되었습니다.' : '저장되었습니다.', 'success');
        closeModal('modal-daily'); loadDailyReports();
      } catch (e) { toast(e.message, 'error'); }
    }
    
    function delDailyReport(id) {
      confirm2('삭제 확인', '이 작업일보를 삭제하시겠습니까?', async () => {
        try {
          await api(`/api/daily-reports/${id}?userId=${currentUser?.id || ''}`, { method: 'DELETE' });
          toast('삭제되었습니다.', 'success');
          loadDailyReports();
        } catch (e) { toast(e.message, 'error'); }
      }, '🗑️ 삭제', 'btn-danger');
    }

    // ── TBM ───────────────────────────────────────────────────
    async function loadTbmList() {
      try {
        const viewAs = document.getElementById('view-as-employee')?.value || '';
        const projId = document.getElementById('filter-tbm-project')?.value || 'all';
        const data = await api(`/api/tbm?userId=${currentUser?.id || ''}&viewAsUserId=${viewAs}&projectId=${projId}`);
        const list = data.tbm_logs || [];
        const tbody = document.getElementById('tbm-tbody');
        const canEdit = currentUser?.role === 'admin';
        if (!list.length) { tbody.innerHTML = `<tr><td colspan="5"><div class="empty-state"><div class="empty-icon">📢</div><p>TBM 기록이 없습니다.</p></div></td></tr>`; return; }
        tbody.innerHTML = list.map(t => {
          const imgs = (t.image_path || '').split(',').filter(x => x.trim());
          return `<tr>
      <td class="fw-600" style="white-space:nowrap;">${esc(t.created_date)}
        <div style="font-size:11px;color:var(--text-muted);font-weight:normal;">작성: ${fmtDate(t.created_at)}</div>
      </td>
      <td style="max-width:300px;white-space:pre-wrap;">${esc((t.work_details_hazards || '').slice(0, 80))}${(t.work_details_hazards || '').length > 80 ? '...' : ''}</td>
      <td style="max-width:200px;">${esc((t.safety_measures || '').slice(0, 60))}${(t.safety_measures || '').length > 60 ? '...' : ''}</td>
      <td class="td-muted">${fmtAuthor(t.creator_name)}</td>
      <td>
        ${imgs.length ? `<div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:6px;">` + imgs.map(img => `
          <div style="display:inline-flex;flex-direction:column;align-items:center;gap:2px;">
            <img src="/uploads/${encodeURIComponent(img.trim())}" alt="TBM 사진" style="max-width:60px;max-height:50px;border-radius:6px;border:1px solid var(--border);cursor:pointer;" onclick="openLightbox('/uploads/${encodeURIComponent(img.trim())}')"/>
            <a href="/uploads/${encodeURIComponent(img.trim())}/download" style="font-size:11px;color:var(--accent);text-decoration:none;">⬇️</a>
          </div>`).join('') + `</div>` : ''}
        <div class="td-actions" style="display:inline-flex;"><button class="btn btn-secondary btn-sm" onclick="openTbmModal('${t.id}')">✏️</button><button class="btn btn-danger btn-sm" onclick="delTbm('${t.id}')">🗑️</button></div>
      </td>
    </tr>`;
        }).join('');
      } catch (e) { toast('TBM 로딩 실패: ' + e.message, 'error'); }
    }
    function openTbmModal(id) {
      editingTbmId = id;
      document.getElementById('tbm-modal-title').textContent = id ? 'TBM 수정' : 'TBM 작성';
      ['tbm-date', 'tbm-hazards', 'tbm-measures', 'tbm-notes'].forEach(i => document.getElementById(i).value = '');
      document.getElementById('tbm-date').value = new Date().toISOString().slice(0, 10);
      if (id) {
        api(`/api/tbm/${id}?userId=${currentUser?.id}`).then(data => {
          const t = data.tbm_log;
          document.getElementById('tbm-date').value = t.created_date || '';
          document.getElementById('tbm-hazards').value = t.work_details_hazards || '';
          document.getElementById('tbm-measures').value = t.safety_measures || '';
          document.getElementById('tbm-notes').value = t.special_notes || '';
        }).catch(e => toast(e.message, 'error'));
      }
      openModal('modal-tbm');
    }
    async function saveTbm() {
      const date = document.getElementById('tbm-date').value;
      const hazards = document.getElementById('tbm-hazards').value.trim();
      const measures = document.getElementById('tbm-measures').value.trim();
      const notes = document.getElementById('tbm-notes').value.trim();
      if (!hazards || !measures) { toast('필수 항목을 입력하세요.', 'error'); return; }
      try {
        const fd = new FormData();
        fd.append('userId', currentUser?.id || '');
        fd.append('created_date', date);
        fd.append('work_details_hazards', hazards);
        fd.append('safety_measures', measures);
        fd.append('special_notes', notes);
        fd.append('creator_name', currentUser?.name || '');
        
        const photoInput = document.getElementById('tbm-photo');
        if (photoInput && photoInput.files) {
          for (let i = 0; i < photoInput.files.length; i++) {
            fd.append('files', photoInput.files[i]);
          }
        }

        const method = editingTbmId ? 'PUT' : 'POST';
        const url = editingTbmId ? `/api/tbm/${editingTbmId}` : '/api/tbm';
        
        // Use standard fetch for FormData
        const res = await fetch(url, { method, body: fd });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || '저장 실패');

        toast(editingTbmId ? '수정되었습니다.' : '작성되었습니다.', 'success');
        closeModal('modal-tbm'); loadTbmList();
      } catch (e) { toast(e.message, 'error'); }
    }
    function delTbm(id) {
      confirm2('TBM 삭제', 'TBM 일지를 삭제하시겠습니까?', async () => {
        try { await api(`/api/tbm/${id}`, { method: 'DELETE', body: JSON.stringify({ userId: currentUser?.id }) }); toast('삭제됨', 'success'); loadTbmList(); } catch (e) { toast(e.message, 'error'); }
      }, '삭제 확인', 'btn-danger');
    }

    // ── Risk Assessments ───────────────────────────────────────
    async function loadRiskAssessments() {
      try {
        const projId = document.getElementById('filter-risk-project')?.value || 'all';
        const data = await api(`/api/risk-assessments?userId=${currentUser?.id || ''}&projectId=${projId}`);
        const list = data.risk_assessments || [];
        const tbody = document.getElementById('risk-tbody');
        if (!list.length) { tbody.innerHTML = `<tr><td colspan="5"><div class="empty-state"><div class="empty-icon">⚠️</div><p>위험성평가 기록이 없습니다.</p></div></td></tr>`; return; }
        tbody.innerHTML = list.map(r => {
          return `<tr>
      <td class="fw-600" style="white-space:nowrap;">${esc(r.eval_date)}</td>
      <td>
        <div style="font-weight:bold;margin-bottom:4px;">${esc(r.task_name)}</div>
        <div style="font-size:12px;color:var(--text-muted);white-space:pre-wrap;">${esc(r.content)}</div>
        ${r.file_path ? `
          <div style="display:inline-flex;flex-direction:column;align-items:center;gap:2px;margin-top:8px;">
            <img src="/uploads/${encodeURIComponent(r.file_path)}" alt="위험성평가 사진" style="max-width:80px;max-height:80px;border-radius:6px;border:1px solid var(--border);cursor:pointer;" onclick="openLightbox('/uploads/${encodeURIComponent(r.file_path)}')"/>
            <a href="/uploads/${encodeURIComponent(r.file_path)}/download" style="font-size:11px;color:var(--accent);text-decoration:none;">⬇️ ${esc(r.file_name || '다운로드')}</a>
          </div>` : ''}
      </td>
      <td class="td-muted">${esc(r.evaluator)}</td>
      <td class="td-muted">${fmtDate(r.created_at)}</td>
      <td>
        <div class="td-actions" style="display:inline-flex;">
          <button class="btn btn-danger btn-sm" onclick="delRisk('${r.id}')">🗑️</button>
        </div>
      </td>
    </tr>`;
        }).join('');
      } catch (e) { toast('위험성평가 로딩 실패: ' + e.message, 'error'); }
    }
    
    function openRiskModal() {
      ['risk-date', 'risk-evaluator', 'risk-task', 'risk-content', 'risk-file'].forEach(i => document.getElementById(i).value = '');
      document.getElementById('risk-date').value = new Date().toISOString().slice(0, 10);
      
      const projSelect = document.getElementById('risk-project');
      projSelect.innerHTML = projectDataList.map(p => `<option value="${p.id}">${esc(p.project_name)}</option>`).join('');
      
      openModal('modal-add-risk');
    }
    
    async function saveRiskAssessment() {
      const projId = document.getElementById('risk-project').value;
      const date = document.getElementById('risk-date').value;
      const evaluator = document.getElementById('risk-evaluator').value.trim();
      const task = document.getElementById('risk-task').value.trim();
      const content = document.getElementById('risk-content').value.trim();
      
      if (!projId || !date || !evaluator || !task || !content) { toast('필수 항목을 모두 입력하세요.', 'error'); return; }
      
      const fileInput = document.getElementById('risk-file');
      
      try {
        const fd = new FormData();
        fd.append('projectId', projId);
        fd.append('evalDate', date);
        fd.append('evaluator', evaluator);
        fd.append('taskName', task);
        fd.append('content', content);
        fd.append('userId', currentUser?.id || '');
        
        if (fileInput && fileInput.files && fileInput.files[0]) {
          fd.append('file', fileInput.files[0]);
        }
        
        const res = await fetch('/api/risk-assessments', { method: 'POST', body: fd });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || '등록 실패');
        
        toast(data.message || '등록되었습니다.', 'success');
        closeModal('modal-add-risk');
        loadRiskAssessments();
      } catch (e) { toast(e.message, 'error'); }
    }
    
    function delRisk(id) {
      confirm2('삭제 확인', '이 위험성평가를 삭제하시겠습니까?', async () => {
        try { await api(`/api/risk-assessments/${id}`, { method: 'DELETE' }); toast('삭제됨', 'success'); loadRiskAssessments(); } catch (e) { toast(e.message, 'error'); }
      }, '삭제 확인', 'btn-danger');
    }

    // ── Work Plans ────────────────────────────────────────────
    async function loadWorkplans() {
      try {
        const viewAs = document.getElementById('view-as-employee')?.value || '';
        const projId = document.getElementById('filter-workplan-project')?.value || 'all';
        const data = await api(`/api/workplans?userId=${currentUser?.id || ''}&viewAsUserId=${viewAs}&projectId=${projId}`);
        const list = data.work_plans || [];
        const tbody = document.getElementById('wp-tbody');
        const canEdit = currentUser?.role === 'admin';
        if (!list.length) { tbody.innerHTML = `<tr><td colspan="5"><div class="empty-state"><div class="empty-icon">📋</div><p>작업계획서가 없습니다.</p></div></td></tr>`; return; }
        const statusLabel = { planned: '<span class="badge badge-blue">계획</span>', in_progress: '<span class="badge badge-amber">진행중</span>', completed: '<span class="badge badge-green">완료</span>' };
        tbody.innerHTML = list.map(w => {
          const imgs = (w.image_path || '').split(',').filter(x => x.trim());
          return `<tr>
      <td class="fw-600" style="white-space:nowrap;">${esc(w.work_date)}
        <div style="font-size:11px;color:var(--text-muted);font-weight:normal;">작성: ${fmtDate(w.created_at)}</div>
      </td>
      <td>${esc((w.work_content || '').slice(0, 80))}</td>
      <td class="td-muted">${fmtAuthor(w.manager_name)}</td>
      <td>${statusLabel[w.status] || w.status}</td>
      <td>
        ${imgs.length ? `<div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:6px;">` + imgs.map(img => `
          <div style="display:inline-flex;flex-direction:column;align-items:center;gap:2px;">
            <img src="/uploads/${encodeURIComponent(img.trim())}" alt="작업 사진" style="max-width:60px;max-height:50px;border-radius:6px;border:1px solid var(--border);cursor:pointer;" onclick="openLightbox('/uploads/${encodeURIComponent(img.trim())}')"/>
            <a href="/uploads/${encodeURIComponent(img.trim())}/download" style="font-size:11px;color:var(--accent);text-decoration:none;">⬇️</a>
          </div>`).join('') + `</div>` : ''}
        <div class="td-actions" style="display:inline-flex;"><button class="btn btn-secondary btn-sm" onclick="openWpModal('${w.id}')">✏️</button><button class="btn btn-danger btn-sm" onclick="delWp('${w.id}')">🗑️</button></div>
      </td>
    </tr>`;
        }).join('');
      } catch (e) { toast('작업계획서 로딩 실패: ' + e.message, 'error'); }
    }
    function openWpModal(id) {
      editingWpId = id;
      document.getElementById('wp-modal-title').textContent = id ? '작업계획서 수정' : '작업계획서 작성';
      ['wp-date', 'wp-content', 'wp-manager'].forEach(i => document.getElementById(i).value = '');
      document.getElementById('wp-date').value = new Date().toISOString().slice(0, 10);
      document.getElementById('wp-status').value = 'planned';
      if (id) {
        api(`/api/workplans/${id}?userId=${currentUser?.id}`).then(data => {
          const w = data.work_plan;
          document.getElementById('wp-date').value = w.work_date || '';
          document.getElementById('wp-content').value = w.work_content || '';
          document.getElementById('wp-manager').value = w.manager_name || '';
          document.getElementById('wp-status').value = w.status || 'planned';
        }).catch(e => toast(e.message, 'error'));
      }
      openModal('modal-wp');
    }
    async function saveWorkplan() {
      const date = document.getElementById('wp-date').value;
      const content = document.getElementById('wp-content').value.trim();
      const manager = document.getElementById('wp-manager').value.trim();
      const status = document.getElementById('wp-status').value;
      
      if (!content) { toast('작업 내용을 입력하세요.', 'error'); return; }
      try {
        const fd = new FormData();
        fd.append('userId', currentUser?.id || '');
        fd.append('work_date', date);
        fd.append('work_content', content);
        fd.append('manager_name', manager);
        fd.append('status', status);

        const photoInput = document.getElementById('wp-photo');
        if (photoInput && photoInput.files) {
          for (let i = 0; i < photoInput.files.length; i++) {
            fd.append('files', photoInput.files[i]);
          }
        }

        const method = editingWpId ? 'PUT' : 'POST';
        const url = editingWpId ? `/api/workplans/${editingWpId}` : '/api/workplans';
        
        const res = await fetch(url, { method, body: fd });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || '저장 실패');

        toast(editingWpId ? '수정되었습니다.' : '작성되었습니다.', 'success');
        closeModal('modal-wp'); loadWorkplans();
      } catch (e) { toast(e.message, 'error'); }
    }
    function delWp(id) {
      confirm2('작업계획서 삭제', '작업계획서를 삭제하시겠습니까?', async () => {
        try { await api(`/api/workplans/${id}`, { method: 'DELETE', body: JSON.stringify({ userId: currentUser?.id }) }); toast('삭제됨', 'success'); loadWorkplans(); } catch (e) { toast(e.message, 'error'); }
      }, '삭제 확인', 'btn-danger');
    }

    // ── Notice ──────────────────────────────────────────
    async function loadNotices() {
      try {
        const data = await api('/api/notices');
        const list = data.notices || [];
        const container = document.getElementById('notice-list');
        const isAdmin = currentUser?.role === 'admin';
        const addBtn = document.getElementById('add-notice-btn');
        if (addBtn) addBtn.style.display = isAdmin ? '' : 'none';
        if (!list.length) {
          container.innerHTML = `<div class="empty-state"><div class="empty-icon">📣</div><p>등록된 공지가 없습니다.</p></div>`;
          return;
        }
        container.innerHTML = list.map(n => `
          <div style="border:1px solid var(--border);border-radius:10px;padding:14px 16px;margin:8px 12px;">
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">
              <span style="font-weight:700;font-size:15px;">${esc(n.title)}</span>
              <span style="font-size:12px;color:var(--text-muted);">${fmtDate(n.created_at)} &nbsp;·&nbsp; ${fmtAuthor(n.author_name)}</span>
            </div>
            ${n.content ? `<p style="color:var(--text-secondary);font-size:13px;white-space:pre-wrap;margin-bottom:8px;">${esc(n.content)}</p>` : ''}
            ${n.file_name ? `<a href="/uploads/${encodeURIComponent(n.file_path)}" target="_blank" style="color:var(--accent);font-size:13px;">&#128206; ${esc(n.file_name)}</a>` : ''}
            ${isAdmin ? `<div style="text-align:right;margin-top:8px;"><button class="btn btn-danger btn-sm" onclick="deleteNotice('${n.id}')">&#128465; 삭제</button></div>` : ''}
          </div>`).join('');
      } catch (e) { toast('공지 로드 실패: ' + e.message, 'error'); }
    }
    function openNoticeModal() { openModal('modal-notice'); ['notice-title','notice-content'].forEach(id => document.getElementById(id).value=''); document.getElementById('notice-file').value=''; }
    async function saveNotice() {
      const title = document.getElementById('notice-title').value.trim();
      if (!title) { toast('제목을 입력하세요.', 'error'); return; }
      try {
        const fd = new FormData();
        fd.append('userId', currentUser?.id || '');
        fd.append('title', title);
        fd.append('content', document.getElementById('notice-content').value.trim());
        const fileInput = document.getElementById('notice-file');
        if (fileInput && fileInput.files && fileInput.files.length > 0) {
          fd.append('file', fileInput.files[0]);
        }
        const res = await fetch('/api/notices', { method: 'POST', body: fd });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || '등록 실패');
        toast('공지가 등록되었습니다.', 'success');
        closeModal('modal-notice'); loadNotices();
      } catch (e) { toast(e.message, 'error'); }
    }
    function deleteNotice(id) {
      confirm2('공지 삭제', '이 공지를 삭제하시겠습니까?', async () => {
        try { await api(`/api/notices/${id}?userId=${currentUser?.id}`, { method: 'DELETE' }); toast('삭제됨', 'success'); loadNotices(); } catch (e) { toast(e.message, 'error'); }
      }, '삭제 확인', 'btn-danger');
    }

    // ── 새 공사 추가 / 수정 ────────────────────────────────────
    function openAddProjectModal() { 
      editingProjectId = null;
      document.getElementById('project-modal-title').textContent = '🏗️ 새 공사 추가';
      ['np-name','np-contractor','np-start','np-end','np-amount','np-manager','np-location'].forEach(id => document.getElementById(id).value=''); 
      openModal('modal-add-project');
    }
    function editProject(id) {
      editingProjectId = id;
      const p = projectDataList.find(x => x.id === id);
      if (!p) return;
      document.getElementById('project-modal-title').textContent = '🏗️ 공사 수정';
      document.getElementById('np-name').value = p.project_name || '';
      document.getElementById('np-contractor').value = p.contractor_name || p.client_name || '';
      document.getElementById('np-start').value = p.start_date || '';
      document.getElementById('np-end').value = p.end_date || '';
      document.getElementById('np-amount').value = p.contract_amount || '';
      document.getElementById('np-manager').value = p.site_manager || '';
      document.getElementById('np-location').value = p.location || p.site_address || '';
      openModal('modal-add-project');
    }
    async function saveNewProject() {
      const name = document.getElementById('np-name').value.trim();
      const contractor = document.getElementById('np-contractor').value.trim();
      const start = document.getElementById('np-start').value.trim();
      const end = document.getElementById('np-end').value.trim();
      const amount = document.getElementById('np-amount').value.trim();
      const manager = document.getElementById('np-manager').value.trim();
      const location = document.getElementById('np-location').value.trim();
      if (!name || !contractor || !start || !end || !amount || !manager || !location) {
        toast('필수 항목을 모두 입력하세요.', 'error'); return;
      }
      try {
        const method = editingProjectId ? 'PUT' : 'POST';
        const url = editingProjectId ? `/api/projects/${editingProjectId}` : '/api/projects';
        await api(url, { method, body: JSON.stringify({
          userId: currentUser?.id,
          project_name: name, contractor_name: contractor,
          start_date: start, end_date: end,
          contract_amount: amount, site_manager: manager, location
        }) });
        toast(editingProjectId ? '공사가 수정되었습니다.' : '공사가 추가되었습니다.', 'success');
        closeModal('modal-add-project'); loadProjectInfo();
      } catch (e) { toast(e.message, 'error'); }
    }
    function deleteProject(id) {
      confirm2('공사 삭제', '정말 삭제하시겠습니까?', async () => {
        try { await api(`/api/projects/${id}`, { method: 'DELETE', body: JSON.stringify({ userId: currentUser?.id }) }); toast('삭제됨', 'success'); loadProjectInfo(); } catch (e) { toast(e.message, 'error'); }
      }, '삭제 확인', 'btn-danger');
    }

    // ── Docs ──────────────────────────────────────────────────
    async function loadDocs() {
      try {
        const data = await api(`/api/documents?userId=${currentUser?.id || ''}`);
        allDocs = data.documents || [];
        renderDocs(allDocs);
      } catch (e) { toast('문서 로딩 실패: ' + e.message, 'error'); }
    }
    function filterDocs() {
      const q = document.getElementById('doc-search').value.toLowerCase();
      const cat = document.getElementById('doc-cat-filter').value;
      renderDocs(allDocs.filter(d => (!q || d.title.toLowerCase().includes(q) || (d.description || '').toLowerCase().includes(q)) && (!cat || d.category === cat)));
    }
    function renderDocs(list) {
      const tbody = document.getElementById('docs-tbody');
      const canEdit = currentUser?.role === 'admin';
      if (!list.length) { tbody.innerHTML = `<tr><td colspan="6"><div class="empty-state"><div class="empty-icon">📁</div><p>문서가 없습니다.</p></div></td></tr>`; return; }
      tbody.innerHTML = list.map(d => `<tr>
    <td style="text-align:center;"><input type="checkbox" class="doc-checkbox" value="${d.id}"></td>
    <td><a href="/uploads/${esc(d.file_path)}" target="_blank" style="color:var(--accent);text-decoration:none;">📄 ${esc(d.title)}</a></td>
    <td><span class="badge badge-blue">${esc(d.category) || '-'}</span></td>
    <td class="td-muted">${fmtAuthor(d.uploader_name)}</td>
    <td class="td-muted" style="white-space:nowrap;">${fmtDate(d.created_at)}</td>
    <td>${canEdit ? `<button class="btn btn-danger btn-sm" onclick="delDoc('${d.id}','${esc(d.title)}')">🗑️</button>` : '-'}</td>
  </tr>`).join('');
      if (!canEdit) document.getElementById('upload-doc-btn').style.display = 'none';
    }
    function openUploadModal() { openModal('modal-upload'); }
    async function uploadDoc() {
      const file = document.getElementById('up-file').files[0];
      const title = document.getElementById('up-title').value.trim();
      if (!file || !title) { toast('문서명과 파일을 선택하세요.', 'error'); return; }
      const fd = new FormData();
      fd.append('file', file);
      fd.append('title', title);
      fd.append('category', document.getElementById('up-cat').value);
      fd.append('description', document.getElementById('up-desc').value);
      fd.append('userId', currentUser?.id || '');
      try {
        const res = await fetch('/api/documents/upload', { method: 'POST', body: fd });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error);
        toast('업로드 완료', 'success'); closeModal('modal-upload'); loadDocs();
      } catch (e) { toast(e.message, 'error'); }
    }
    async function deleteSelectedDocs() {
      const cbs = document.querySelectorAll('#docs-tbody .doc-checkbox:checked');
      if (!cbs.length) { toast('삭제할 문서를 선택하세요.', 'error'); return; }
      const ids = Array.from(cbs).map(cb => cb.value);
      confirm2('선택 삭제', `선택한 ${ids.length}개의 문서를 영구 삭제하시겠습니까?`, async () => {
        try {
          const data = await api('/api/documents/delete-multiple', { method: 'DELETE', body: JSON.stringify({ userId: currentUser?.id, docIds: ids }) });
          toast('삭제되었습니다.', 'success'); loadDocs();
        } catch (e) { toast(e.message, 'error'); }
      }, '🗑️ 삭제 확인', 'btn-danger');
    }
    function delDoc(id, title) {
      confirm2('문서 삭제', `"${title}" 문서를 삭제하시겠습니까?`, async () => {
        try { await api(`/api/documents/${id}`, { method: 'DELETE', body: JSON.stringify({ userId: currentUser?.id }) }); toast('삭제됨', 'success'); loadDocs(); } catch (e) { toast(e.message, 'error'); }
      }, '삭제 확인', 'btn-danger');
    }

    // ── Audit Log ─────────────────────────────────────────────
    async function loadAuditLog() {
      try {
        const data = await api(`/api/audit-logs?userId=${currentUser?.id || ''}`);
        const list = data.logs || [];
        const tbody = document.getElementById('audit-tbody');
        if (!list.length) { tbody.innerHTML = `<tr><td colspan="5"><div class="empty-state"><p>로그 없음</p></div></td></tr>`; return; }
        tbody.innerHTML = list.map(l => `<tr>
      <td class="td-muted" style="white-space:nowrap;">${fmtDate(l.timestamp)}</td>
      <td class="fw-600">${fmtAuthor(l.user_name)}</td>
      <td><span class="badge badge-gray">${esc(l.user_role)}</span></td>
      <td><span class="badge badge-blue">${esc(l.action)}</span></td>
      <td class="td-muted">${esc(l.details)}</td>
    </tr>`).join('');
      } catch (e) { }
    }

    // ── 날짜 자동 포맷 (YYYYMMDD → YYYY-MM-DD) ──────────────────
    function autoFormatDate(input) {
      let v = input.value.replace(/[^0-9]/g, '');
      if (v.length >= 8) {
        v = v.slice(0, 8);
        input.value = `${v.slice(0, 4)}-${v.slice(4, 6)}-${v.slice(6, 8)}`;
      } else if (v.length > 4) {
        input.value = `${v.slice(0, 4)}-${v.slice(4)}`;
      } else {
        input.value = v;
      }
    }

    // ── 금액 자동 콤마 ───────────────────────────────────────────
    function autoFormatAmount(input) {
      let v = input.value.replace(/[^0-9]/g, '');
      if (v) input.value = parseInt(v, 10).toLocaleString('ko-KR');
      else input.value = '';
    }

    // ── 관리자: 직원별 보기 필터 ─────────────────────────────────
    async function loadEmployeeFilter() {
      try {
        const data = await api(`/api/auth/employees?userId=${currentUser?.id || ''}`);
        const sel = document.getElementById('view-as-employee');
        sel.innerHTML = '<option value="">\uc804\uccb4 \ubcf4\uae30</option>';
        (data.employees || []).filter(e => e.status === 'active').forEach(e => {
          const opt = document.createElement('option');
          opt.value = e.id;
          opt.textContent = `${e.name} (${e.department || '-'})`;
          sel.appendChild(opt);
        });
      } catch (e) { }
    }
    function onViewAsChange() {
      const page = document.querySelector('.page.active')?.id?.replace('page-', '');
      if (page) {
        const loaders = { dashboard: loadDashboard, project: loadProjectInfo, 'completed-projects': loadProjectInfo, workers: loadWorkers, workplan: loadWorkplans, daily: loadDailyReports, tbm: loadTbmList, risk: loadRiskAssessments, docs: loadDocs, auditlog: loadAuditLog, accounts: loadAccountsPending, notice: loadNotices };
        if (loaders[page]) loaders[page]();
      }
    }

    // ── Enter key login ───────────────────────────────────────
    document.addEventListener('keydown', e => {
      if (e.key === 'Enter') {
        const ap = document.getElementById('panel-admin');
        const ep = document.getElementById('panel-empl');
        if (ap && ap.classList.contains('active')) doLogin('admin');
        else if (ep && ep.classList.contains('active')) doLogin('employee');
      }
    });
  