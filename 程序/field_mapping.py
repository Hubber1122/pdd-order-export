# -*- coding: utf-8 -*-
"""
拼多多买家订单导出 —— 字段映射定义（按真实接口响应校准）

真实响应结构（order_list_v4，2026-10 实测）：
  { "server_time": ..., "orders": [ { ...订单... } ], "extra_info": {...}, "view_list": [] }

每个订单（下划线命名）：
  order_sn          订单号          parent_order_sn   母订单号(多单合并时)
  group_order_id    团订单号(19位)  order_amount      实付金额(分)
  shipping_amount   运费(分)        discount_amount   优惠金额(分)
  display_amount    展示金额(分)    order_time        下单时间(秒)
  shipping_time     发货时间        receive_time      签收时间
  tracking_number   运单号          order_status_prompt 状态中文文案
  order_link_url    订单详情链接    offset            分页游标(MO-01-xxx)
  order_goods[]     商品列表: goods_id / sku_id / goods_name / goods_price(分)
                              goods_number / thumb_url / spec
  group_order{}     拼单信息: success_time / create_at
  mall{}            店铺: mall_name / logo
  extra_info.order_hint{}  物流: message / extra_map.pdd_status / metric_info.express_status

说明：
  - 收货人姓名/电话/地址在「订单列表接口」中不返回（仅 address_id），原软件此类字段
    在无数据时同样留空；如需收货人需另调订单详情接口（后续可扩展）。
  - 应付金额(originalTotal) = order_amount + discount_amount（原价）。
"""

FIELD_MAPPING = [
    # ---- level 0：订单/商品主信息 ----
    {"name": "orderId", "label": "订单编号", "level": 0, "width": 27,
     "paths": ["order_sn", "orderSn", "order_snH"], "type": "str"},
    {"name": "parentOrderSn", "label": "母订单编号", "level": 0, "width": 26,
     "paths": ["group_order_id", "groupOrderId", "parent_order_sn", "parentOrderSn"], "type": "str"},
    {"name": "srcOrderId", "label": "原始订单", "level": 0, "width": 24,
     "paths": ["source_biz_sn", "srcOrderId"], "type": "str"},
    {"name": "productTitle", "label": "商品名称", "level": 0, "width": 30,
     "paths": ["order_goods.[].goods_name", "goods_name"], "type": "goods_join"},
    {"name": "productUrl", "label": "商品链接", "level": 0, "width": 30,
     "paths": ["order_goods.[].goods_id", "goods_id"], "type": "goods_url"},
    {"name": "checkoutUrl", "label": "结算链接", "level": 0, "width": 30,
     "paths": [], "type": "str"},
    {"name": "commentsUrl", "label": "评价链接", "level": 0, "width": 30,
     "paths": [], "type": "str"},
    {"name": "detailUrl", "label": "详情链接", "level": 0, "width": 30,
     "paths": ["order_link_url", "orderLinkUrl"], "type": "order_url"},
    {"name": "productPic", "label": "商品主图", "level": 0, "width": 30,
     "paths": ["order_goods.[].thumb_url", "thumb_url"], "type": "goods_join"},
    {"name": "productId", "label": "商品ID", "level": 0, "width": 17,
     "paths": ["order_goods.[].goods_id", "goods_id"], "type": "goods_join"},
    {"name": "skuInfo", "label": "属性SKU", "level": 0, "width": 17,
     "paths": ["order_goods.[].spec", "spec"], "type": "goods_join"},
    {"name": "skuId", "label": "SKU ID", "level": 0, "width": 17,
     "paths": ["order_goods.[].sku_id", "sku_id"], "type": "goods_join"},
    {"name": "quantity", "label": "数量", "level": 0, "width": 5,
     "paths": ["order_goods.[].goods_number", "goods_number"], "type": "goods_sum"},
    {"name": "realPrice", "label": "商品单价", "level": 0, "width": 9,
     "paths": ["order_goods.[].goods_price", "goods_price"], "type": "goods_join_amount"},
    {"name": "postFee", "label": "运费", "level": 0, "width": 8,
     "paths": ["shipping_amount", "shippingAmount"], "type": "amount"},
    {"name": "actualFee", "label": "实际付款", "level": 0, "width": 9,
     "paths": ["order_amount", "display_amount", "orderAmount"], "type": "amount"},
    {"name": "originalTotal", "label": "应付金额", "level": 0, "width": 9,
     "paths": ["order_amount"], "type": "original_total"},
    {"name": "tradeStatus", "label": "交易状态", "level": 0, "width": 16,
     "paths": ["order_status_prompt", "orderStatusPrompt", "status"], "type": "status"},
    {"name": "latestLogistics", "label": "最新物流", "level": 0, "width": 20,
     "paths": ["extra_info.order_hint.message"], "type": "str"},
    {"name": "logisticsStatus", "label": "物流状态", "level": 0, "width": 9,
     "paths": ["extra_info.order_hint.extra_map.pdd_status"], "type": "str"},
    {"name": "logisticsStatusCode", "label": "状态代码", "level": 0, "width": 13,
     "paths": ["extra_info.order_hint.metric_info.express_status"], "type": "str"},
    {"name": "logisticsNumber", "label": "运单号", "level": 0, "width": 20,
     "paths": ["tracking_number", "trackingNumber"], "type": "str"},
    {"name": "orderTime", "label": "创建时间", "level": 0, "width": 17,
     "paths": ["order_time", "orderTime"], "type": "timestamp"},
    {"name": "shippingTime", "label": "发货时间", "level": 0, "width": 17,
     "paths": ["shipping_time", "shippingTime"], "type": "timestamp"},
    {"name": "receiveTime", "label": "签收时间", "level": 0, "width": 17,
     "paths": ["receive_time", "receiveTime"], "type": "timestamp"},
    {"name": "shopName", "label": "店铺名称", "level": 0, "width": 20,
     "paths": ["mall.mall_name", "mall.mallName", "mall_name", "mall.name"], "type": "str"},
    {"name": "invoiceStatus", "label": "发票状态", "level": 0, "width": 9,
     "paths": [], "type": "str"},
    {"name": "nick", "label": "买家号", "level": 0, "width": 17,
     "paths": [], "type": "str"},

    # ---- level 1：收货/付款（列表接口不含收货人，留空） ----
    {"name": "rechargeNumber", "label": "充值号码", "level": 1, "width": 10,
     "paths": ["recharge_number"], "type": "str"},
    {"name": "receiverName", "label": "收货人姓名", "level": 1, "width": 11,
     "paths": ["receiver_name", "receiverName"], "type": "str"},
    {"name": "receiverPhone", "label": "收货电话", "level": 1, "width": 13,
     "paths": ["receiver_phone", "receiverPhone", "mobile"], "type": "str", "need_decrypt": True},
    {"name": "receiverProvince", "label": "省", "level": 1, "width": 10,
     "paths": ["receiver_province", "province_name"], "type": "str"},
    {"name": "receiverCity", "label": "市", "level": 1, "width": 10,
     "paths": ["receiver_city", "city_name"], "type": "str"},
    {"name": "receiverDistrict", "label": "区县", "level": 1, "width": 10,
     "paths": ["receiver_district", "district_name"], "type": "str"},
    {"name": "addressDetail", "label": "详细地址", "level": 1, "width": 20,
     "paths": ["receiver_address", "full_address", "address_detail"], "type": "str"},
    {"name": "payTime", "label": "拼单时间", "level": 1, "width": 17,
     "paths": ["group_order.success_time", "success_time", "group_order.create_at"], "type": "timestamp"},
    {"name": "payType", "label": "支付方式", "level": 1, "width": 10,
     "paths": [], "type": "str"},
    {"name": "memo", "label": "备注", "level": 1, "width": 20,
     "paths": ["buyer_memo", "remark"], "type": "str"},

    # ---- level 3：物流 ----
    {"name": "postmanName", "label": "快递员姓名", "level": 3, "width": 11,
     "paths": [], "type": "str"},
    {"name": "postmanContact", "label": "快递员电话", "level": 3, "width": 13,
     "paths": [], "type": "str"},
    {"name": "logisticsCompany", "label": "物流公司", "level": 3, "width": 20,
     "paths": ["extra_info.order_hint.message"], "type": "express_company"},
    {"name": "addressInfo", "label": "地址信息", "level": 3, "width": 20,
     "paths": [], "type": "str"},
    {"name": "extraLogistics", "label": "补充物流", "level": 3, "width": 20,
     "paths": [], "type": "str"},
    {"name": "cabinetAddress", "label": "代收点地址", "level": 3, "width": 20,
     "paths": [], "type": "str"},
    {"name": "cabinetCompany", "label": "代收点名称", "level": 3, "width": 20,
     "paths": [], "type": "str"},
    {"name": "cabinetCode", "label": "取件码", "level": 3, "width": 11,
     "paths": [], "type": "str"},
]


# 交易状态码 -> 中文（兜底；优先用 order_status_prompt 中文文案）
TRADE_STATUS_MAP = {
    "1": "待付款", "2": "待发货", "3": "待收货", "4": "待评价", "5": "待分享",
    "0": "全部", "6": "已完成", "7": "已取消",
}


def get_headers():
    return [f["name"] for f in FIELD_MAPPING]


def get_labels():
    return [f["label"] for f in FIELD_MAPPING]
