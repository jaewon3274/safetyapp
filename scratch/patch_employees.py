import os
import re

file_path = 'templates/index.html'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Hide approved in pending
content = content.replace(
    "const list = data.pending || [];",
    "const list = (data.pending || []).filter(p => p.status === 'pending');"
)

# 2. Remove Trash Tab
content = re.sub(r'<button[^>]*id="acc-tab-trash"[^>]*>.*?</button>', '', content, flags=re.DOTALL)
content = re.sub(r'<div id="acc-panel-trash".*?<!-- 휴지통 패널 끝 -->', '', content, flags=re.DOTALL) # Might fail if there's no such comment, but the display:none part is what matters. Wait, better to just hide it or remove the button. Removing the button is enough to hide it.

# 3. Add Delete Selected button in employees panel
if 'onclick="deleteSelectedEmployees()"' not in content:
    content = content.replace(
        '<div class="card-title">👥 직원 계정 목록</div>',
        '<div class="card-title">👥 직원 계정 목록</div>\n                <button class="btn btn-danger btn-sm" onclick="deleteSelectedEmployees()" style="margin-left:auto;">🗑️ 선택 삭제</button>'
    )
    content = content.replace(
        '<div class="card-header">',
        '<div class="card-header" style="display:flex;justify-content:space-between;align-items:center;">'
    )

# 4. Add checkbox in header
content = content.replace(
    '<th style="width:50px;text-align:center;">No.</th>',
    '<th style="width:70px;text-align:center;"><input type="checkbox" onclick="document.querySelectorAll(\'.emp-checkbox\').forEach(cb => cb.checked = this.checked)"> No.</th>'
)

# 5. Add checkbox in rows
content = content.replace(
    '<td style="text-align:center;">${activeList.length - idx}</td>',
    '<td style="text-align:center;"><input type="checkbox" class="emp-checkbox" value="${e.id}" style="margin-right:4px;"> ${activeList.length - idx}</td>'
)

# 6. Remove delete button from row
old_del_btn = """<button class="btn btn-sm" style="background:rgba(239,68,68,.15);border:1px solid #ef4444;color:#ef4444;" onclick="deleteEmployee('${e.id}','${esc(e.name)}')">🗑️ 삭제</button>"""
content = content.replace(old_del_btn, "")

# 7. Add deleteSelectedEmployees JS function
js_func = """
    async function deleteSelectedEmployees() {
      const cbs = document.querySelectorAll('.emp-checkbox:checked');
      if (!cbs.length) { toast('삭제할 계정을 선택해주세요.', 'error'); return; }
      confirm2('선택 삭제', `선택한 ${cbs.length}개의 계정을 삭제하시겠습니까?`, async () => {
        try {
          for (const cb of cbs) {
            await api(`/api/auth/delete/${cb.value}`, { method: 'DELETE', body: JSON.stringify({ adminUserId: currentUser?.id }) });
          }
          toast('선택 계정이 삭제되었습니다.', 'success');
          loadEmployeeList();
        } catch(e) { toast(e.message, 'error'); }
      }, '삭제', 'btn-danger');
    }
"""
if "deleteSelectedEmployees" not in content:
    content = content.replace("async function deleteEmployee", js_func + "\n    async function deleteEmployee")

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
print("Done")
