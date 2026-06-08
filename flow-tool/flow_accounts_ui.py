# -*- coding: utf-8 -*-
"""Trang quản lý tài khoản Flow (HTML cho /accounts)."""

ACCOUNTS_HTML = r"""<!DOCTYPE html>
<html lang="vi"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Flow Accounts</title>
<style>
*{box-sizing:border-box} body{font-family:Segoe UI,Arial,sans-serif;margin:0;background:#0f172a;color:#e2e8f0}
.wrap{max-width:1000px;margin:0 auto;padding:20px}
h1{font-size:20px;margin:0 0 4px} .sub{color:#94a3b8;font-size:13px;margin-bottom:16px}
.card{background:#1e293b;border:1px solid #334155;border-radius:12px;padding:16px;margin-bottom:16px}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
input,select,button{font:inherit;padding:8px 10px;border-radius:8px;border:1px solid #475569;background:#0f172a;color:#e2e8f0}
button{cursor:pointer;border-color:#3b82f6;background:#1d4ed8;color:#fff}
button.gray{background:#334155;border-color:#475569} button.red{background:#b91c1c;border-color:#dc2626}
button.green{background:#15803d;border-color:#16a34a}
table{width:100%;border-collapse:collapse;margin-top:8px} th,td{text-align:left;padding:8px;border-bottom:1px solid #334155;font-size:13px}
.badge{padding:2px 8px;border-radius:999px;font-size:12px;font-weight:600}
.b-ready{background:#14532d;color:#86efac} .b-login{background:#7c2d12;color:#fdba74}
.b-cool{background:#1e3a8a;color:#93c5fd} .b-err{background:#7f1d1d;color:#fca5a5}
.b-idle{background:#334155;color:#cbd5e1}
.muted{color:#94a3b8;font-size:12px}
</style></head><body><div class="wrap">
<h1>🎨 Flow Accounts — xoay vòng đa tài khoản</h1>
<div class="sub">Base URL cho tool vẽ: <b>http://localhost:8790</b> · Acc sẵn sàng: <b id="ready">-</b></div>

<div class="card">
  <b>➕ Thêm tài khoản</b>
  <div class="row" style="margin-top:10px">
    <input id="name" placeholder="Tên acc (vd flow01)" style="flex:1;min-width:160px">
    <select id="browser"></select>
    <select id="mode">
      <option value="dedicated">Thư mục riêng (đăng nhập mới)</option>
      <option value="existing">Dùng profile có sẵn</option>
    </select>
    <select id="profile" style="display:none;min-width:160px"></select>
    <button onclick="addAcc()">Thêm</button>
  </div>
  <div class="muted" style="margin-top:6px">Dedicated = tool tạo thư mục riêng, bấm "Đăng nhập" rồi sign-in Google 1 lần. Existing = dùng profile Chrome/CocCoc bạn đã có (cần đóng trình duyệt đó khi chạy).</div>
</div>

<div class="card">
  <b>📥 Nạp cookie trực tiếp (KHÔNG cần mở trình duyệt)</b>
  <div class="muted" style="margin:6px 0">Dán cookie labs.google: chuỗi header <code>name=value; ...</code> (DevTools ▸ Network ▸ request labs.google ▸ Cookie), hoặc JSON export từ extension <b>Cookie-Editor</b>, hoặc cookies.txt. Cần có <code>__Secure-next-auth.session-token</code>. Hoặc thả file <code>&lt;tên&gt;.txt</code>/<code>.json</code> vào thư mục <code>cookies/</code> rồi bấm "Nạp từ thư mục".</div>
  <div class="row">
    <input id="imp_name" placeholder="Tên acc (mới hoặc đã có)" style="min-width:200px">
    <button class="gray" onclick="reloadCookies()">📂 Nạp từ thư mục cookies/</button>
    <button class="gray" onclick="showLog()">📜 Xem log</button>
  </div>
  <textarea id="imp_raw" placeholder="Dán cookie vào đây..." style="width:100%;min-height:90px;margin-top:8px;font:13px monospace;padding:8px;border-radius:8px;border:1px solid #475569;background:#0f172a;color:#e2e8f0"></textarea>
  <div class="row" style="margin-top:8px"><button class="green" onclick="importCookie()">Nạp / Cập nhật cookie</button></div>
</div>

<div class="card" id="logcard" style="display:none">
  <div class="row" style="justify-content:space-between"><b>📜 Log</b><button class="gray" onclick="document.getElementById('logcard').style.display='none'">Đóng</button></div>
  <pre id="logbox" style="max-height:280px;overflow:auto;background:#0f172a;border:1px solid #334155;border-radius:8px;padding:10px;font-size:12px;white-space:pre-wrap"></pre>
</div>

<div class="card">
  <div class="row" style="justify-content:space-between">
    <b>📋 Danh sách tài khoản</b>
    <button class="gray" onclick="load()">↻ Làm mới</button>
  </div>
  <table><thead><tr><th>Tên</th><th>Trình duyệt</th><th>Trạng thái</th><th>Dùng/Lỗi</th><th>Hành động</th></tr></thead>
  <tbody id="tb"></tbody></table>
</div>

<script>
let BROWSERS={};
async function api(m,u,b){const r=await fetch(u,{method:m,headers:{'Content-Type':'application/json'},body:b?JSON.stringify(b):undefined});return r.json();}
async function loadBrowsers(){
  const d=await api('GET','/api/accounts/browsers');BROWSERS=d.browsers;
  const bs=document.getElementById('browser');bs.innerHTML='';
  Object.keys(BROWSERS).forEach(k=>{const o=document.createElement('option');o.value=k;o.textContent=k+(BROWSERS[k].installed?'':' (chưa cài)');bs.appendChild(o);});
  bs.onchange=fillProfiles;document.getElementById('mode').onchange=onMode;fillProfiles();
}
function onMode(){document.getElementById('profile').style.display=document.getElementById('mode').value==='existing'?'':'none';fillProfiles();}
function fillProfiles(){
  const b=document.getElementById('browser').value;const ps=(BROWSERS[b]||{}).profiles||[];
  const sel=document.getElementById('profile');sel.innerHTML='';
  ps.forEach(p=>{const o=document.createElement('option');o.value=p.dir;o.textContent=p.name+(p.email?' · '+p.email:'')+' ['+p.dir+']';sel.appendChild(o);});
}
async function addAcc(){
  const name=document.getElementById('name').value.trim();if(!name){alert('Nhập tên');return;}
  const mode=document.getElementById('mode').value;
  const body={name,browser:document.getElementById('browser').value,mode};
  if(mode==='existing')body.profile_directory=document.getElementById('profile').value;
  const r=await api('POST','/api/accounts',body);if(!r.ok){alert(r.error||'lỗi');return;}
  document.getElementById('name').value='';load();
}
function badge(s){const m={ready:['b-ready','sẵn sàng'],login_needed:['b-login','cần đăng nhập'],cooldown:['b-cool','cooldown'],error:['b-err','lỗi'],starting:['b-idle','đang mở'],idle:['b-idle','chưa mở']};const x=m[s]||['b-idle',s];return '<span class="badge '+x[0]+'">'+x[1]+'</span>';}
async function act(m,u){await api(m,u);load();}
async function login(id){const r=await api('POST','/api/accounts/'+id+'/login');alert(r.message||r.error||'Đã mở cửa sổ. Đăng nhập xong bấm Kiểm tra.');load();}
async function check(id){const r=await api('POST','/api/accounts/'+id+'/check');alert(r.logged_in?'✓ Đã đăng nhập Flow':'✗ Chưa đăng nhập');load();}
async function importCookie(){
  const name=document.getElementById('imp_name').value.trim();
  const raw=document.getElementById('imp_raw').value.trim();
  if(!name){alert('Nhập tên acc');return;}
  if(!raw){alert('Dán cookie vào ô bên dưới');return;}
  const r=await api('POST','/api/accounts/import',{name,raw});
  if(!r.ok){alert('Lỗi: '+(r.error||'?'));return;}
  alert((r.has_session?'✓ ':'⚠ ')+'Đã nạp '+r.count+' cookie cho "'+name+'".'+(r.has_session?' Acc sẵn sàng.':' THIẾU session-token → chưa dùng được.'));
  document.getElementById('imp_raw').value='';load();
}
function prefillImport(name){document.getElementById('imp_name').value=name;document.getElementById('imp_raw').focus();window.scrollTo(0,0);}
async function reloadCookies(){const r=await api('POST','/api/accounts/reload-cookies');alert('Đã nạp từ '+ (r.loaded||0) +' file trong thư mục cookies/.');load();}
async function showLog(){const r=await api('GET','/api/logs?n=200');document.getElementById('logbox').textContent=(r.lines||[]).join('\n')||'(trống)';document.getElementById('logcard').style.display='';}
async function status(id){
  const r=await api('GET','/api/accounts/'+id+'/status');const s=r.status||{};
  let msg='Email: '+(s.email||'?')+'\nĐăng nhập: '+(s.logged_in?'có':'không')+'\nHết hạn phiên: '+(s.expires||'?')+'\nĐiểm/Quota: '+JSON.stringify(s.credits);
  if(s.error)msg+='\nLỗi: '+s.error;
  alert(msg);load();
}
async function load(){
  const d=await api('GET','/api/accounts');document.getElementById('ready').textContent=d.ready;
  const tb=document.getElementById('tb');tb.innerHTML='';
  (d.accounts||[]).forEach(a=>{
    const tr=document.createElement('tr');
    let cd=a.cooldown>0?(' '+a.cooldown+'s'):'';
    tr.innerHTML='<td><b>'+a.name+'</b><div class="muted">'+a.mode+' · '+a.profile_directory+'</div></td>'+
      '<td>'+a.browser+'<div class="muted">:'+a.port+'</div></td>'+
      '<td>'+badge(a.status)+cd+(a.logged_in?' 🔑':'')+'</td>'+
      '<td>'+a.uses+' / '+a.failures+'</td>'+
      '<td class="row">'+
        '<button class="green" onclick="login(\''+a.id+'\')">Đăng nhập</button>'+
        '<button class="gray" onclick="prefillImport(\''+a.name+'\')">📥 Nạp cookie</button>'+
        '<button class="gray" onclick="check(\''+a.id+'\')">Kiểm tra</button>'+
        '<button class="gray" onclick="status(\''+a.id+'\')">Điểm/Quota</button>'+
        '<button class="gray" onclick="act(\'POST\',\'/api/accounts/'+a.id+'/start\')">Mở</button>'+
        (a.enabled?'<button class="gray" onclick="act(\'POST\',\'/api/accounts/'+a.id+'/disable\')">Tắt</button>':'<button class="green" onclick="act(\'POST\',\'/api/accounts/'+a.id+'/enable\')">Bật</button>')+
        '<button class="red" onclick="if(confirm(\'Xóa?\'))act(\'DELETE\',\'/api/accounts/'+a.id+'\')">Xóa</button>'+
      '</td>';
    tb.appendChild(tr);
  });
}
loadBrowsers();load();setInterval(load,5000);
</script>
</div></body></html>"""
