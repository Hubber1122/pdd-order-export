# -*- coding: utf-8 -*-
"""
拼多多买家订单导出 —— 数据获取与字段解析

还原原软件原生侧 `ExportPddOrders` 的取数逻辑：
  直连 `order_list_v4` 接口（POST JSON），按 offset/page/size 分页，
  解析返回 JSON，按字段映射提取订单数据。

由于拼多多接口字段名存在 camelCase / snake_case 多种变体，
本模块对每个导出字段提供多候选路径（见 field_mapping.py），并按优先级取值，
以最大化还原原始实现的字段映射结果。
"""

import json
import time
import datetime
import re
import requests

from field_mapping import FIELD_MAPPING, TRADE_STATUS_MAP
from pdd_decrypt import decrypt_phone

# 拼多多移动端 UA（还原原软件指纹伪装目标）
MOBILE_UA = ("Mozilla/5.0 (Linux; Android 10; Pixel 3 XL Build/QQ3A.200805.001; wv) "
             "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/89.0.4389.114 "
             "Mobile Safari/537.36")

# 风控/限流状态码 -> 中文提示
RISK_MESSAGES = {
    424: "触发拼多多风控（424）。多为短时间请求过多所致，请等待 1~2 小时后重试；"
         "若持续出现，请在 config.json 补充 anti_content 反爬头（见 README 第六节）。",
    429: "请求过于频繁（429），请稍后再试。",
    403: "访问被拒绝（403），凭证可能已失效或触发风控，请重新登录获取凭证。",
    401: "未授权（401），登录凭证已失效，请重新登录获取。",
}

ORDER_LIST_URL = "https://mobile.yangkeduo.com/proxy/api/api/aristotle/order_list_v4?pdduid={pdduid}"
ORDER_LIST_SEARCH_URL = "https://mobile.yangkeduo.com/proxy/api/api/aristotle/order_list_search_v4?pdduid={pdduid}"
ORDERS_PAGE_URL = "https://mobile.yangkeduo.com/orders.html"


def _get_path(node, path):
    """按点号路径取值，支持 goodsList.[].key 聚合形式返回列表。"""
    if node is None:
        return None
    if "[]" in path:
        # 形如 goodsList.[].goodsName
        arr_key, _, rest = path.partition("[]")
        arr_key = arr_key.rstrip(".")
        rest = rest.lstrip(".")
        arr = node.get(arr_key) if isinstance(node, dict) else None
        if isinstance(arr, list):
            vals = [_get_path(it, rest) for it in arr]
            return vals
        return None
    cur = node
    for key in path.split("."):
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return None
    return cur


def _first_nonempty(node, paths):
    """按优先级返回第一个非空值。"""
    for p in paths:
        v = _get_path(node, p)
        if v is not None and v != "":
            return v
    return None


def _fmt_amount(v):
    """金额：拼多多接口以「分」返回，统一转「元」（保留 2 位）。"""
    if v is None or v == "":
        return ""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v
    # 若明显是小数（元）则直接保留；否则按分处理
    if abs(f - round(f)) > 1e-9:
        return f"{f:.2f}"
    return f"{f / 100.0:.2f}"


def _fmt_timestamp(v):
    """Unix 时间戳 -> 'yyyy-MM-dd HH:mm:ss'（兼容秒/毫秒）。"""
    if v is None or v == "":
        return ""
    try:
        t = float(v)
    except (TypeError, ValueError):
        return v
    if t > 1e12:
        t /= 1000.0
    try:
        return datetime.datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return v


def _fmt_status(v):
    """交易状态码 -> 中文描述。"""
    if v is None:
        return ""
    s = str(v)
    if s in TRADE_STATUS_MAP:
        return TRADE_STATUS_MAP[s]
    return v


def _join(vals, sep="/"):
    """聚合多商品值（去重、去空、转字符串）。"""
    if vals is None:
        return ""
    if not isinstance(vals, list):
        vals = [vals]
    out = []
    seen = set()
    for v in vals:
        if v is None or v == "":
            continue
        sv = str(v)
        if sv not in seen:
            seen.add(sv)
            out.append(sv)
    return sep.join(out)


def _join_amount(vals):
    """多商品金额聚合：每项分转元后拼接。"""
    if vals is None:
        return ""
    if not isinstance(vals, list):
        vals = [vals]
    parts = [_fmt_amount(v) for v in vals if v is not None and v != ""]
    return "/".join(parts)


def _sum_amount(vals):
    """多商品数量求和。"""
    if vals is None:
        return ""
    if not isinstance(vals, list):
        vals = [vals]
    total = 0
    for v in vals:
        try:
            total += int(v)
        except (TypeError, ValueError):
            pass
    return str(total)


def _goods_url(vals):
    """商品链接：若为纯商品 ID 则拼 goods.html，否则直接返回。"""
    if vals is None:
        return ""
    if not isinstance(vals, list):
        vals = [vals]
    out = []
    for v in vals:
        if v is None or v == "":
            continue
        s = str(v)
        if s.isdigit():
            s = f"https://mobile.yangkeduo.com/goods.html?goods_id={s}"
        out.append(s)
    return "/".join(out)


def _order_url(v):
    """订单详情链接：order_link_url 为相对路径，拼完整域名。"""
    if v is None or v == "":
        return ""
    s = str(v)
    if s.startswith("http"):
        return s
    return "https://mobile.yangkeduo.com/" + s.lstrip("/")


def _original_total(v, order):
    """应付金额（原价）= 实付 + 优惠（均为分）。"""
    try:
        paid = int(order.get("order_amount") or v or 0)
        disc = int(order.get("discount_amount") or 0)
        return f"{(paid + disc) / 100.0:.2f}"
    except (TypeError, ValueError):
        return _fmt_amount(v)


def _express_company(v, order):
    """从物流信息文本中提取物流公司名（如「韵达快递」「极兔速递」）。"""
    if v is None:
        return ""
    m = re.search(r"\|\s*([^：:｜|]+?)[：:]", str(v))
    if m:
        return m.group(1).strip()
    # 兜底：直接找常见快递名
    for name in ("顺丰", "韵达", "中通", "圆通", "申通", "极兔", "邮政", "百世", "京东"):
        if name in str(v):
            return name + "快递"
    return ""


_TYPE_HANDLERS = {
    "str": lambda v, order=None: "" if v is None else str(v),
    "amount": lambda v, order=None: _fmt_amount(v),
    "timestamp": lambda v, order=None: _fmt_timestamp(v),
    "status": lambda v, order=None: _fmt_status(v),
    "goods_join": lambda v, order=None: _join(v),
    "goods_join_amount": lambda v, order=None: _join_amount(v),
    "goods_sum": lambda v, order=None: _sum_amount(v),
    "goods_url": lambda v, order=None: _goods_url(v),
    "order_url": lambda v, order=None: _order_url(v),
    "original_total": _original_total,
    "express_company": _express_company,
}


def extract_order(order, mapping=None, need_decrypt=False, web_spider_rule=None):
    """
    从单个订单 JSON 中提取一行数据。

    order       : 订单 dict
    mapping     : 字段映射（默认取 FIELD_MAPPING）
    need_decrypt: 是否对手机号字段尝试解密
    web_spider_rule: 手机号解密规则（当 need_decrypt 时使用）
    返回 OrderedDict(name -> value)
    """
    from collections import OrderedDict
    if mapping is None:
        mapping = FIELD_MAPPING
    row = OrderedDict()
    for field in mapping:
        name = field["name"]
        v = _first_nonempty(order, field["paths"])
        handler = _TYPE_HANDLERS.get(field["type"], lambda x, order=None: x)
        try:
            v = handler(v, order)
        except TypeError:
            v = handler(v)
        # 手机号解密
        if field.get("need_decrypt") and need_decrypt and web_spider_rule:
            try:
                v = decrypt_phone(v, web_spider_rule)
            except Exception:
                pass
        row[name] = "" if v is None else v
    return row


class PddOrderClient:
    """拼多多订单导出客户端。"""

    def __init__(self, pdduid, access_token, verify_auth_token=None,
                 anti_content=None, anti_token=None, timeout=20, session=None):
        self.pdduid = pdduid
        self.access_token = access_token
        self.verify_auth_token = verify_auth_token
        self.anti_content = anti_content
        self.anti_token = anti_token
        self.timeout = timeout
        self.session = session or requests.Session()

    def _headers(self, referer=ORDERS_PAGE_URL):
        h = {
            "User-Agent": MOBILE_UA,
            "Content-Type": "application/json;charset=UTF-8",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": referer,
            "Origin": "https://mobile.yangkeduo.com",
            "X-Requested-With": "XMLHttpRequest",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "Cookie": f"PDDAccessToken={self.access_token}",
        }
        if self.verify_auth_token:
            h["Cookie"] += f"; VerifyAuthToken={self.verify_auth_token}"
        if self.anti_token:
            h["anti-token"] = self.anti_token
        if self.anti_content:
            h["anti-content"] = self.anti_content
        return h

    def fetch_page(self, post_data):
        """请求一页订单，返回解析后的 result dict（含订单列表与分页信息）。"""
        url = ORDER_LIST_URL.format(pdduid=self.pdduid)
        resp = self.session.post(url, data=json.dumps(post_data, ensure_ascii=False),
                                 headers=self._headers(), timeout=self.timeout)
        if resp.status_code in RISK_MESSAGES:
            raise RuntimeError(RISK_MESSAGES[resp.status_code])
        resp.raise_for_status()
        return resp.json()

    def fetch_all(self, order_type="all", start_offset=None, max_pages=0,
                  page_size=10, progress=None, keyword=None, debug_dir=None,
                  page_delay=0.6, raw_sink=None):
        """
        分页拉取全部订单。

        order_type   : all / 1(待付款) / 2(待发货) / 3(待收货) / 4(待评价) / 5(待分享)
        start_offset : 起始订单号（形如 210524-529672510313396 或 MO-01-xxx）
        max_pages    : 最大页数（0 表示不限，拉到底）
        page_size    : 每页条数
        progress     : 可选回调 progress(page_no, total_so_far)
        keyword      : 订单关键词（走搜索接口）
        debug_dir    : 可选目录，保存前几页原始响应 JSON（用于校准字段）
        返回 (orders, meta) —— orders 为扁平化订单 dict 列表，meta 含分页信息
        """
        post_data = {
            "origin_host_name": "mobile.yangkeduo.com",
            "page": 1,
            "size": page_size,
            "type": order_type,
        }
        if start_offset:
            post_data["offset"] = start_offset
        if keyword:
            post_data["keyWord"] = keyword
            post_data["key_word"] = keyword

        orders = []
        seen_keys = set()
        page = 1
        HARD_PAGE_LIMIT = 1000  # 绝对安全上限，防止分页异常导致无限拉取
        while True:
            if (max_pages and page > max_pages) or page > HARD_PAGE_LIMIT:
                break
            try:
                result = self.fetch_page(post_data)
            except Exception as e:
                raise RuntimeError(f"请求第 {page} 页失败: {e}")
            if progress:
                progress(page, len(orders))

            batch = _extract_orders(result)
            if not batch:
                break

            # 按订单号去重 + 死循环防护：
            # 若本页订单全部已出现过，说明游标无效（接口忽略 offset）或已到底，立即停止
            new_batch = []
            for o in batch:
                key = (o.get("orderSn") or o.get("order_sn")
                       or o.get("orderId") or o.get("order_id")
                       or str(sorted(o.items()))[:120])
                if key not in seen_keys:
                    seen_keys.add(key)
                    new_batch.append(o)
            if not new_batch:
                break
            # 大部分重复（>60%）说明游标翻页异常，取新增后停止
            if len(new_batch) < len(batch) * 0.4:
                orders.extend(new_batch)
                break
            orders.extend(new_batch)

            # 保存调试响应（前 5 页）：写入文件 + 内存收集双保险
            if page <= 5:
                if raw_sink is not None:
                    raw_sink.append(result)
                if debug_dir:
                    _save_debug(debug_dir, page, result)

            has_more, next_offset = _pagination(result)
            if has_more is None:
                # 兜底：响应未给出 has_more 时，本页满页则假设还有下一页
                has_more = len(batch) >= page_size
            if not next_offset:
                # 兜底：用最后一条订单的 offset 游标（真实字段，形如 MO-01-<订单号>）
                last = batch[-1]
                for k in ("offset", "sort_id", "order_sn", "orderSn"):
                    if last.get(k):
                        next_offset = last[k]
                        break
            if not has_more:
                break
            post_data["page"] = page + 1
            if next_offset:
                post_data["offset"] = next_offset
            page += 1
            # 页间延时，降低触发风控的概率
            if page_delay:
                time.sleep(page_delay)

        return orders, {"pages": page, "has_more": False, "last_raw": None}


def _extract_orders(result):
    """从 order_list_v4 响应中提取订单列表（兼容多种字段结构）。"""
    if not isinstance(result, dict):
        return []
    # 常见容器：result.orders / result.orderList / result.groupOrderList / orders
    candidates = []
    r = result.get("result") or result.get("data") or result
    if isinstance(r, dict):
        for key in ("orders", "orderList", "order_list", "groupOrderList",
                    "groupOrder", "list", "items", "orderInfoList"):
            if isinstance(r.get(key), list):
                candidates.append(r[key])
    if isinstance(result.get("orders"), list):
        candidates.append(result["orders"])
    for c in candidates:
        if c:
            return _flatten_orders(c)
    return []


def _flatten_orders(orders):
    """把可能带 groupOrder/orderInfo 包装的订单列表拍平。"""
    out = []
    for o in orders:
        if not isinstance(o, dict):
            continue
        # 有些接口把订单放在 order.groupOrder / order.orderInfo
        inner = o.get("groupOrder") or o.get("orderInfo") or o.get("order") or o
        if isinstance(inner, dict) and inner is not o:
            inner = {**inner, **{k: v for k, v in o.items() if k not in inner}}
        out.append(inner)
    return out


def _pagination(result):
    """
    从响应中解析分页信息。

    返回 (has_more, next_offset)：
      has_more   True/False —— 明确取自响应字段
                 None       —— 响应中无该字段（由调用方兜底判断）
      next_offset 下一页游标（可为 None，由调用方兜底取最后一条订单号）
    """
    if not isinstance(result, dict):
        return None, None
    has_more = None
    next_offset = None
    # 依次在 result / data / 顶层 三层中查找
    for container in (result.get("result"), result.get("data"), result):
        if not isinstance(container, dict):
            continue
        for k in ("has_more", "hasMore", "has_next", "hasNext"):
            if k in container:
                has_more = bool(container[k])
                break
        for k in ("next_offset", "nextOffset", "next_cursor", "nextCursor"):
            if container.get(k):
                next_offset = container[k]
                break
        if has_more is not None or next_offset:
            break
    return has_more, next_offset


def _save_debug(debug_dir, page, result):
    """保存原始响应 JSON，便于校准字段映射。"""
    try:
        os.makedirs(debug_dir, exist_ok=True)
        path = os.path.join(debug_dir, f"page_{page}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
