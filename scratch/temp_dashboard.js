async function loadDashboard() {
1944:       try {
1945:         const [statsData, noticesData, projData] = await Promise.all([
1946:           api(`/api/stats?userId=${currentUser?.id || ''}`).catch(() => ({})),
1947:           api('/api/notices').catch(() => ({})),
1948:           api('/api/project-info').catch(() => ({}))
1949:         ]);
1950:         if (projData.project) {
1951:           document.getElementById('proj-name-label').textContent = projData.project.project_name || '공사명 미등록';
1952:         }
1953:         const s = statsData.stats || {};
1954:         document.getElementById('stat-docs').textContent = s.total_documents ?? '-';
1955:         document.getElementById('stat-workers').textContent = s.total_workers ?? '-';
1956:         document.getElementById('stat-tbm').textContent = s.total_tbm ?? '-';
1957:         document.getElementById('stat-workplans').textContent = s.total_workplans ?? '-';
1958:         
1959:         const notices = (noticesData.notices || []).slice(0, 10);
1960:         const tbody = document.getElementById('dash-notice-tbody');
1961:         if (!notices.length) { tbody.innerHTML = `<tr><td colspan="4"><div class="empty-state"><p>최근 등록된 글이 없습니다.</p></div></td></tr>`; return; }
1962:         tbody.innerHTML = notices.map(n => `<tr>
1963:       <td class="fw-600">${esc(n.title)}</td>
1964:       <td class="td-muted">${fmtAuthor(n.author_name)}</td>
1965:       <td class="td-muted" style="white-space:nowrap;">${fmtDate(n.created_at)}</td>
1966:       <td>${n.file_name ? `<a href="/uploads/${encodeURIComponent(n.file_path)}" target="_blank" style="color:var(--accent);font-size:13px;">📎 다운로드</a>` : '-'}</td>
1967:     </tr>`).join('');
1968:       } catch (e) { }
1969:     }
1970: 
1971:     // ── Project Info ──────────────────────────────────────────
1972:     let projectDataList = [];
1973:     let editingProjectId = null;
1974: 
1975:     async function loadProjectDropdowns() {
1976:       try {
1977:         const viewAs = document.getElementById('view-as-employee')?.value || '';
1978:         const data = await api(`/api/project-info?userId=${currentUser?.id || ''}&viewAsUserId=${viewAs}`);
1979:         const projects = data.projects || [];
1980:         const options = '<option value="all">전체 현장</option>' + projects.map(p => `<option value="${p.id}">${esc(p.project_name)}</option>`).join('');
1981:         ['filter-workers-project', 'filter-workplan-project', 'filter-tbm-project'].forEach(id => {
1982:           const el = document.getElementById(id);
1983:           if (el) el.innerHTML = options;
1984:         });
1985:       } catch (e) { console.error('Project dropdown load failed', e); }
1986:     }
1987:     
1988:     