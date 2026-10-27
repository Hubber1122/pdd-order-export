// 拼多多登录助手 —— 后台服务脚本（MV3 Service Worker）
// 职责：读取/监听拼多多 Cookie（PDDAccessToken、pdd_user_id），响应 popup 请求。

const LOGIN_URL =
  "https://mobile.yangkeduo.com/login.html?from=https%3A%2F%2Fmobile.yangkeduo.com%2Forders.html&refer_page_name=my_order";

// 需要提取的 Cookie 名称（按优先级）
const TOKEN_KEYS = ["PDDAccessToken", "AccessToken", "PASS_ID"];
const UID_KEYS = ["pdd_user_id", "pdd_user_uin", "duoduo_id"];

// 从 Cookie 中读取凭证
async function readCredentials() {
  let token = "";
  let uid = "";
  try {
    const cookies = await chrome.cookies.getAll({
      domain: ".yangkeduo.com",
    });
    for (const c of cookies) {
      if (!token && TOKEN_KEYS.includes(c.name)) {
        token = c.value;
      }
      if (!uid && UID_KEYS.includes(c.name)) {
        uid = c.value;
      }
    }
  } catch (e) {
    // 忽略读取失败
  }
  return { token, uid, loggedIn: !!token };
}

// 监听 Cookie 变化，登录成功后广播给 popup
chrome.cookies.onChanged.addListener(async (changeInfo) => {
  const name = changeInfo.cookie && changeInfo.cookie.name;
  if (!name) return;
  const isToken = TOKEN_KEYS.includes(name);
  const isUid = UID_KEYS.includes(name);
  if (!isToken && !isUid) return;

  if (isToken && !changeInfo.removed) {
    // PDDAccessToken 写入 = 登录成功，主动通知 popup
    const cred = await readCredentials();
    try {
      await chrome.runtime.sendMessage({ type: "LOGIN_DETECTED", ...cred });
    } catch (e) {
      // popup 未打开时 sendMessage 会失败，忽略
    }
  }
});

// 响应 popup 消息
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  (async () => {
    switch (msg.type) {
      case "OPEN_LOGIN": {
        await chrome.tabs.create({ url: LOGIN_URL });
        sendResponse({ ok: true });
        break;
      }
      case "GET_CREDENTIALS": {
        const cred = await readCredentials();
        sendResponse({ ok: true, ...cred });
        break;
      }
      case "SAVE_MANUAL": {
        // 手动注入：保存到 storage（备用方案）
        await chrome.storage.local.set({
          manualToken: msg.token || "",
          manualUid: msg.uid || "",
        });
        sendResponse({ ok: true });
        break;
      }
      case "GET_MANUAL": {
        const data = await chrome.storage.local.get(["manualToken", "manualUid"]);
        sendResponse({ ok: true, ...data });
        break;
      }
      default:
        sendResponse({ ok: false, message: "unknown" });
    }
  })();
  return true; // 异步响应
});
