// 拼多多登录助手 —— popup 逻辑
let cachedToken = "";
let cachedUid = "";

const $ = (id) => document.getElementById(id);

// 更新界面上的凭证显示
function render(token, uid) {
  cachedToken = token || "";
  cachedUid = uid || "";

  const status = $("status");
  const statusText = $("statusText");
  const tokenVal = $("tokenVal");
  const uidVal = $("uidVal");

  if (cachedToken) {
    status.classList.add("on");
    statusText.textContent = "已登录，凭证已就绪";
  } else {
    status.classList.remove("on");
    statusText.textContent = "尚未登录，请先打开登录页";
  }

  if (cachedUid) {
    uidVal.textContent = cachedUid;
    uidVal.classList.remove("empty");
  } else {
    uidVal.textContent = "—";
    uidVal.classList.add("empty");
  }

  if (cachedToken) {
    tokenVal.textContent = cachedToken;
    tokenVal.classList.remove("empty");
  } else {
    tokenVal.textContent = "—";
    tokenVal.classList.add("empty");
  }
}

// 从 background 读取凭证
async function refresh() {
  try {
    const resp = await chrome.runtime.sendMessage({ type: "GET_CREDENTIALS" });
    if (resp && resp.ok) {
      render(resp.token, resp.uid);
    }
  } catch (e) {
    // ignore
  }
}

// 复制到剪贴板
async function copyText(text, btn) {
  if (!text) {
    btn.textContent = "无内容";
    setTimeout(() => (btn.textContent = "复制"), 1200);
    return;
  }
  try {
    await navigator.clipboard.writeText(text);
    btn.textContent = "已复制";
    btn.classList.add("done");
  } catch (e) {
    // 兜底：用 textarea
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
    btn.textContent = "已复制";
    btn.classList.add("done");
  }
  setTimeout(() => {
    btn.textContent = "复制";
    btn.classList.remove("done");
  }, 1500);
}

// 事件绑定
$("btnLogin").addEventListener("click", async () => {
  await chrome.runtime.sendMessage({ type: "OPEN_LOGIN" });
  window.close();
});

$("btnRefresh").addEventListener("click", refresh);

document.querySelectorAll(".copy").forEach((btn) => {
  btn.addEventListener("click", () => {
    const target = btn.dataset.target;
    copyText(target === "token" ? cachedToken : cachedUid, btn);
  });
});

// 手动凭证
$("manualToggle").addEventListener("click", () => {
  const input = $("manualInput");
  const save = $("btnManualSave");
  input.classList.toggle("hidden");
  save.classList.toggle("hidden");
});

$("btnManualSave").addEventListener("click", async () => {
  const raw = $("manualInput").value.trim();
  if (!raw) return;
  try {
    const data = JSON.parse(raw);
    const token = data.token || data.PDDAccessToken || "";
    const uid = data.uid || data.pdd_user_id || "";
    await chrome.runtime.sendMessage({
      type: "SAVE_MANUAL",
      token,
      uid,
    });
    render(token, uid);
    $("manualInput").value = "";
  } catch (e) {
    alert("格式错误，请按 {\"uid\":\"...\",\"token\":\"...\"} 填写");
  }
});

// 监听后台广播的登录成功事件
chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === "LOGIN_DETECTED") {
    render(msg.token, msg.uid);
  }
});

// 打开 popup 时先读取一次，并读取手动保存的凭证
(async () => {
  await refresh();
  const manual = await chrome.runtime.sendMessage({ type: "GET_MANUAL" });
  if (manual && manual.ok && !cachedToken && manual.manualToken) {
    render(manual.manualToken, manual.manualUid);
  }
})();
