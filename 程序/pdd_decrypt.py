# -*- coding: utf-8 -*-
"""
拼多多收货人手机号解密模块

还原原软件 `js/pdd-mobile-parser.js` 中 `parseMobile` 的解密逻辑。
拼多多为反爬，对收货人手机号等敏感字段返回「密文 + web_spider_rule」，
本模块还原其中四种解密算法：

  web_spider_rule 结构：
    [32 位指纹][1 位算法版本][secret][|jsonpath1|jsonpath2|...]
  算法版本（索引 34 处的字符）：
    1 -> AES-128-CBC + PKCS7（secret = 索引 35~99 的 64 字符）
    2 -> S 自定义 base64 变体（secret = 64 字符映射表）
    3 -> E 标准 base64 + 旋转（secret = 1 位旋转偏移）
    4 -> C 标准 base64 + 逐位替换（secret = 2 位替换参数）
"""

import base64

try:
    from Crypto.Cipher import AES
    _HAS_AES = True
except Exception:  # pragma: no cover
    _HAS_AES = False

_STD_B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"


def _str_padding(s, length, pad="0"):
    """等价于 JS 的 str_padding(e, t, r)：左填充到指定长度。"""
    s = str(s)
    if length - len(s) <= 0:
        return s
    return pad * (length - len(s)) + s


def _w(bytes_list):
    """等价于 JS 的 w()：UTF-8 字节序列 -> 字符串。"""
    try:
        return bytes(bytes_list).decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _decrypt_aes(ciphertext, secret):
    """算法版本 1：AES-128-CBC + PKCS7，ciphertext 为 Base64。"""
    if not _HAS_AES:
        raise RuntimeError("缺少 pycryptodome，无法 AES 解密，请执行 pip install pycryptodome")
    n = secret[:32]
    o = secret[32:]
    a = list(n[:16])
    l = list(n[16:])
    s = list(o[:16])
    u = list(o[16:])
    key = "".join(a[int(c, 16)] for c in s)
    iv = "".join(l[int(c, 16)] for c in u)
    raw = base64.b64decode(ciphertext)
    cipher = AES.new(key.encode("utf-8"), AES.MODE_CBC, iv.encode("utf-8"))
    plain = cipher.decrypt(raw)
    pad = plain[-1]
    return plain[:-pad].decode("utf-8", errors="ignore")


def _decrypt_s(ciphertext, secret):
    """算法版本 2：S 自定义 base64 变体。secret 为 64 字符映射表。"""
    table = {"=": 0}
    for idx, ch in enumerate(secret):
        table[ch] = idx
    bits = ""
    for ch in ciphertext:
        idx = table.get(ch, 0)
        bits += _str_padding(bin(idx)[2:], 6)
    out = []
    for i in range(len(bits) - 8, -1, -8):
        c = int(bits[i:i + 8], 2)
        if c == 0 and not out:
            continue
        out.insert(0, c)
    return _w(out)


def _decrypt_e(ciphertext, secret):
    """算法版本 3：E 标准 base64 + 旋转。secret 为 1 位旋转偏移。"""
    table = {"=": 0}
    for idx, ch in enumerate(_STD_B64):
        table[ch] = idx
    bits = ""
    for ch in ciphertext:
        idx = table.get(ch, 0)
        bits += _str_padding(bin(idx)[2:], 6)
    # 去掉尾部 0 bit
    for i in range(len(bits) - 8, -1, -8):
        if int(bits[i:i + 8], 2) != 0:
            bits = bits[:i + 8]
            break
    a = int(secret) % len(bits)
    bits = bits[a:] + bits[:a]
    out = [int(bits[j:j + 8], 2) for j in range(0, len(bits), 8)]
    return _w(out)


def _decrypt_c(ciphertext, secret):
    """算法版本 4：C 标准 base64 + 逐位替换。secret 为 2 位替换参数。"""
    table = {"=": 0}
    for idx, ch in enumerate(_STD_B64):
        table[ch] = idx
    bits = ""
    for ch in ciphertext:
        idx = table.get(ch, 0)
        bits += _str_padding(bin(idx)[2:], 6)
    s = ""
    for i in range(len(bits) - 8, -1, -8):
        c = int(bits[i:i + 8], 2)
        if c == 0 and not s:
            continue
        s = chr(c) + s
    f = int(secret[0], 16)
    p = int(secret[1], 16)

    def h(ch):
        t = int(ch, 16)
        return format((t - p) if t >= p else (t + 16 - p), "x")

    m = []
    for g in range(0, len(s), 4):
        b = s[g:g + 4]
        if len(b) > f:
            b = b[:f] + h(b[f]) + b[f + 1:]
        m.append(b)
    return _w([int(x, 16) for x in "".join(m)])


_DECRYPTORS = {
    "1": _decrypt_aes,
    "2": _decrypt_s,
    "3": _decrypt_e,
    "4": _decrypt_c,
}


def parse_mobile(data):
    """
    解析手机号接口返回，还原明文手机号。

    参数 data 为接口返回的 dict，须含 `web_spider_rule` 字段；
    密文手机号本身已按 web_spider_rule 中的 jsonpath 定位在 data 内。
    返回解析后的 data（原地解密 jsonpath 指向的字段）。
    """
    if not isinstance(data, dict):
        return data
    rule = data.get("web_spider_rule")
    if not isinstance(rule, str):
        return data

    version = rule[34:35]
    paths = rule[100:].split("|")
    if version not in _DECRYPTORS:
        return data

    if version in ("1", "2"):
        secret = rule[35:99]
    elif version == "3":
        secret = rule[35:36]
    else:
        secret = rule[35:37]

    decryptor = _DECRYPTORS[version]

    for path in paths:
        if not path:
            continue
        keys = [k for k in path.lstrip("$").strip(".").split(".") if k]
        # 定位到密文字段
        node = data
        for k in keys:
            if isinstance(node, dict) and k in node:
                node = node[k]
            else:
                node = None
                break
        if node is None:
            continue
        try:
            node = decryptor(node, secret)
        except Exception:
            node = None
        # 回写（按 keys 定位）
        cur = data
        for k in keys[:-1]:
            if isinstance(cur, dict):
                cur = cur[k]
        if isinstance(cur, dict):
            cur[keys[-1]] = node
    return data


def decrypt_phone(ciphertext, web_spider_rule):
    """
    快捷入口：给定密文与 web_spider_rule，返回明文。
    """
    if not isinstance(web_spider_rule, str) or len(web_spider_rule) < 100:
        return ciphertext
    version = web_spider_rule[34:35]
    if version not in _DECRYPTORS:
        return ciphertext
    if version in ("1", "2"):
        secret = web_spider_rule[35:99]
    elif version == "3":
        secret = web_spider_rule[35:36]
    else:
        secret = web_spider_rule[35:37]
    try:
        return _DECRYPTORS[version](ciphertext, secret)
    except Exception:
        return ciphertext
