"""
协议文档信息 — 从原始协议提取的报文事实，作为 build 的唯一信息源。

每条报文包含路径查找所需的最小信息:
- 路由键值 (func/dir for 645, afn/di/direction/has_address for CSG)
- 数据域字段名列表 (用于自动填充默认值)
"""

# ═══════════════════════════════════════════════════════════════
# DLT645-2007
# ═══════════════════════════════════════════════════════════════

DLT645_MESSAGES = [
    # (func, name, direction, desc, request_fields, response_fields, frame_defaults)
    {
        "func": 0x08, "name": "broadcast_time",
        "direction": "downlink",
        "description": "广播校时",
        "request_fields": ["datetime"],
        "frame_defaults": {"address": "999999999999"},
    },
    {
        "func": 0x11, "name": "read_data",
        "direction": "both",
        "description": "读数据",
        "request_fields": ["di"],
        "response_fields": ["di"],  # + DI 变体字段
    },
    {
        "func": 0x12, "name": "read_follow",
        "direction": "both",
        "description": "读后续数据",
        "request_fields": ["di"],
        "response_fields": ["follow_data"],
    },
    {
        "func": 0x13, "name": "read_address",
        "direction": "both",
        "description": "读通信地址",
        "request_fields": [],                     # L=00H 无数据域
        "response_fields": ["address_data"],
        "frame_defaults": {"address": "AAAAAAAAAAAA"},  # 请求用广播地址
        "response_frame_defaults": {},  # 应答用实际地址 (与 data 一致)
    },
    {
        "func": 0x14, "name": "write_data",
        "direction": "both",
        "description": "写数据",
        "request_fields": ["di", "password", "operator_code", "payload"],
        "response_fields": ["status"],
    },
    {
        "func": 0x15, "name": "write_address",
        "direction": "both",
        "description": "写通信地址",
        "request_fields": ["new_address", "password", "operator_code"],
        "response_fields": ["status"],
        "frame_defaults": {"address": "000000000000"},
    },
    {
        "func": 0x16, "name": "freeze",
        "direction": "both",
        "description": "冻结命令",
        "request_fields": ["freeze_type", "freeze_time"],
        "response_fields": ["status"],
        "frame_defaults": {"address": "000000000000"},
    },
    {
        "func": 0x17, "name": "change_baudrate",
        "direction": "both",
        "description": "更改通信速率",
        "request_fields": ["baud_rate"],
        "response_fields": ["status"],
    },
    {
        "func": 0x18, "name": "change_password",
        "direction": "both",
        "description": "修改密码",
        "request_fields": ["password_info"],
        "response_fields": ["new_password"],
    },
    {
        "func": 0x19, "name": "clear_demand",
        "direction": "both",
        "description": "最大需量清零",
        "request_fields": ["password", "operator_code"],
        "response_fields": ["status"],
    },
    {
        "func": 0x1A, "name": "clear_meter",
        "direction": "both",
        "description": "电表清零",
        "request_fields": ["password", "operator_code"],
        "response_fields": ["status"],
    },
    {
        "func": 0x1B, "name": "clear_event",
        "direction": "both",
        "description": "事件清零",
        "request_fields": ["event_type", "password", "operator_code"],
        "response_fields": ["status"],
    },
    {
        "func": 0x1C, "name": "relay_control",
        "direction": "both",
        "description": "跳合闸/报警/保电",
        "request_fields": ["control_word", "password", "operator_code"],
        "response_fields": ["status"],
    },
    {
        "func": 0x03, "name": "security_auth",
        "direction": "both",
        "description": "安全认证",
        "request_fields": ["auth_type", "auth_data"],
        "response_fields": ["auth_result", "auth_data"],
    },
    {
        "func": 0x1D, "name": "output_control",
        "direction": "both",
        "description": "多功能端子输出控制",
        "request_fields": ["control_word", "password", "operator_code"],
        "response_fields": ["status"],
    },
]

# DLT645 DI 变体 (用于 read_data_response 的 di_data 子路由)
DLT645_DI_VARIANTS = [
    ("00010000", "日冻结时间",       ["freeze_year", "freeze_month", "freeze_day", "freeze_hour"]),
    ("00010001", "月冻结时间",       ["freeze_year", "freeze_month", "freeze_day", "freeze_hour"]),
    ("0001FF00", "正向有功总电能",    ["energy"]),
    ("00010100", "正向有功费率1",     ["energy"]),
    ("00010200", "正向有功费率2",     ["energy"]),
    ("00010300", "正向有功费率3",     ["energy"]),
    ("00010400", "正向有功费率4",     ["energy"]),
    ("0002FF00", "反向有功总电能",    ["energy"]),
    ("0003FF00", "正向无功总电能",    ["energy"]),
    ("0004FF00", "反向无功总电能",    ["energy"]),
    ("0001FF01", "正向有功总电能5B",  ["energy"]),
    ("0101FF00", "正向有功总需量",    ["demand", "demand_time"]),
    ("02010100", "A相电压",         ["voltage"]),
    ("02010200", "B相电压",         ["voltage"]),
    ("02010300", "C相电压",         ["voltage"]),
    ("02020100", "A相电流",         ["current"]),
    ("02020200", "B相电流",         ["current"]),
    ("02020300", "C相电流",         ["current"]),
    ("02030000", "总有功功率",       ["power"]),
    ("02030100", "A相有功功率",      ["power"]),
    ("02060000", "总功率因数",       ["power_factor"]),
    ("03020000", "电网频率",         ["frequency"]),
    ("04000401", "电表通信地址",     ["address"]),
    ("04000501", "电表运行状态字1",  ["status"]),
    ("04000101", "当前日期时间",     ["datetime"]),
    ("0501FF00", "日冻结正向有功电能", ["energy"]),
    ("04060001", "负荷记录块",       ["record_count", "records"]),
]

# DLT645 字段默认值
DLT645_FIELD_DEFAULTS = {
    "datetime":      "260621203000",     # YYMMDDhhmmss
    "freeze_time":   "2606212030",       # YYMMDDhhmm
    "freeze_year":   "26",
    "freeze_month":  "06",
    "freeze_day":    "21",
    "freeze_hour":   "20",
    "demand_time":   "0621203010",       # YYMMDDhhmm (5 bytes = 10 digits)
    "di":            "00010000",
    "address_data":  "000000000001",
    "new_address":   "000000000002",
    "baud_rate":     0x04,
    "password":      "00000000",
    "password_info": "0000000000000000",
    "new_password":  "11111111",
    "operator_code": "00000001",
    "auth_type":     1,
    "auth_result":   "0000",
    "control_word":  0x01,
    "status":        "0000",            # hex string for status fields
    "event_type":    "00991B01",
    "event_data":    "AABB",
    "follow_data":   bytes([0x11,0x22,0x33,0x44]),
    "auth_data":     bytes([0x11,0x22,0x33,0x44]),
    "payload":       bytes([0xAA,0xBB]),
    "energy":        {"raw": "1234567890"},      # BCD numeric raw hex (5 bytes, works for both 4 and 5)
    "demand":        {"raw": "12345678"},        # BCD numeric raw hex
    "voltage":       {"raw": "0220"},             # 2 bytes BCD numeric
    "current":       {"raw": "005000"},           # 3 bytes BCD numeric
    "power":         {"raw": "000500"},           # 3 bytes BCD numeric
    "power_factor":  {"raw": "0950"},             # BCD numeric raw hex (0.950)
    "frequency":     {"raw": "5000"},             # BCD numeric raw hex (50.00)
    "address":       "000000000001",
    "record_count":  2,
    "records":       bytes([0x01,0x02]),
    # struct 类型
    "password_struct": {"pa": "04", "p0": "00", "p1": "00", "p2": "00"},
    "password":       "00000000",            # hex 类型 (4 bytes)
    "password_info":  "0000000000000000",    # hex 类型 (8 bytes)
    "control_word_dict": {
        "direct_close": 0, "allow_close": 1, "direct_trip": 0,
        "delay_trip_timeout": 1, "trip_auto_restore": 0,
        "delay_trip_current": 0, "reserved": 0,
        "power_protection": 0, "power_protection_release": 0,
        "alarm": 0, "alarm_release": 0,
    },
}


# ═══════════════════════════════════════════════════════════════
# CSG 2016 集中器 — 表4
# ═══════════════════════════════════════════════════════════════

CSG_MESSAGES = [
    # (name, afn, fn, di, direction, has_address, desc, request_fields, response_fields)
    {
        "name": "afn00_ack",
        "afn": 0x00, "fn": 1, "di": "E8010001",
        "direction": "uplink", "has_address": False,
        "description": "确认 (ACK)",
        "response_fields": ["result"],
    },
    {
        "name": "afn00_nak",
        "afn": 0x00, "fn": 2, "di": "E8010002",
        "direction": "uplink", "has_address": False,
        "description": "否认 (NAK)",
        "response_fields": ["error_code"],
    },
    {
        "name": "afn01_reset_hardware",
        "afn": 0x01, "fn": 1, "di": "E8020101",
        "direction": "downlink", "has_address": False,
        "description": "复位硬件",
    },
    {
        "name": "afn01_init_archive",
        "afn": 0x01, "fn": 2, "di": "E8020102",
        "direction": "downlink", "has_address": False,
        "description": "初始化档案",
    },
    {
        "name": "afn01_init_task",
        "afn": 0x01, "fn": 3, "di": "E8020103",
        "direction": "downlink", "has_address": False,
        "description": "初始化任务",
    },
    {
        "name": "afn02_add_task",
        "afn": 0x02, "fn": 1, "di": "E8020201",
        "direction": "downlink", "has_address": True,
        "description": "添加任务",
        "request_fields": ["address_area.adst", "payload"],
    },
    {
        "name": "afn02_delete_task",
        "afn": 0x02, "fn": 2, "di": "E8020202",
        "direction": "downlink", "has_address": False,
        "description": "删除任务",
        "request_fields": ["task_id"],
    },
    {
        "name": "afn02_query_remaining",
        "afn": 0x02, "fn": 3, "di": "E8000203",
        "direction": "downlink", "has_address": False,
        "description": "查询未完成任务数",
    },
    {
        "name": "afn02_query_remaining_resp",
        "afn": 0x02, "fn": 3, "di": "E8000103",
        "direction": "uplink", "has_address": False,
        "description": "返回查询未完成任务数",
        "response_fields": ["task_count"],
    },
    {
        "name": "afn02_query_task_list",
        "afn": 0x02, "fn": 4, "di": "E8030204",
        "direction": "downlink", "has_address": False,
        "description": "查询未完成任务列表",
        "request_fields": ["start_task_index", "query_task_count"],
    },
    {
        "name": "afn02_query_task_list_resp",
        "afn": 0x02, "fn": 4, "di": "E8040204",
        "direction": "uplink", "has_address": False,
        "description": "返回查询未完成任务列表",
        "response_fields": ["reported_task_count", "task_ids"],
    },
    {
        "name": "afn03_query_vendor",
        "afn": 0x03, "fn": 1, "di": "E8000301",
        "direction": "downlink", "has_address": False,
        "description": "查询厂商代码和版本信息",
    },
    {
        "name": "afn03_query_mode",
        "afn": 0x03, "fn": 2, "di": "E8000302",
        "direction": "downlink", "has_address": False,
        "description": "查询本地通信模块运行模式信息",
    },
    {
        "name": "afn03_query_master_addr",
        "afn": 0x03, "fn": 3, "di": "E8000303",
        "direction": "downlink", "has_address": False,
        "description": "查询主节点地址",
    },
    {
        "name": "afn03_query_delay",
        "afn": 0x03, "fn": 4, "di": "E8030304",
        "direction": "downlink", "has_address": False,
        "description": "查询通信延时时长",
    },
    {
        "name": "afn03_query_delay_resp",
        "afn": 0x03, "fn": 4, "di": "E8040304",
        "direction": "uplink", "has_address": False,
        "description": "返回查询通信延时时长",
        "response_fields": ["delay_time"],
    },
    {
        "name": "afn04_event_report_ctl",
        "afn": 0x04, "fn": 4, "di": "E8020404",
        "direction": "downlink", "has_address": False,
        "description": "允许/禁止上报从节点事件",
        "request_fields": ["enable"],
    },
    {
        "name": "afn04_active_register",
        "afn": 0x04, "fn": 5, "di": "E8020405",
        "direction": "downlink", "has_address": False,
        "description": "激活从节点主动注册",
    },
    {
        "name": "afn04_stop_register",
        "afn": 0x04, "fn": 6, "di": "E8020406",
        "direction": "downlink", "has_address": False,
        "description": "终止从节点主动注册",
    },
    {
        "name": "afn05_report_task_data",
        "afn": 0x05, "fn": 1, "di": "E8050501",
        "direction": "uplink", "has_address": True,
        "description": "上报任务数据",
        "response_fields": ["task_id", "payload_length", "payload"],
    },
    {
        "name": "afn05_report_slave_event",
        "afn": 0x05, "fn": 2, "di": "E8050502",
        "direction": "uplink", "has_address": True,
        "description": "上报从节点事件",
        "response_fields": ["payload_length", "payload"],
    },
    {
        "name": "afn05_report_slave_info",
        "afn": 0x05, "fn": 3, "di": "E8050503",
        "direction": "uplink", "has_address": False,
        "description": "上报从节点信息",
        "response_fields": ["slave_count", "slave_addrs"],
    },
    {
        "name": "afn05_report_register_end",
        "afn": 0x05, "fn": 4, "di": "E8050504",
        "direction": "uplink", "has_address": False,
        "description": "上报从节点注册结束",
    },
    {
        "name": "afn05_report_task_status",
        "afn": 0x05, "fn": 5, "di": "E8050505",
        "direction": "uplink", "has_address": False,
        "description": "上报任务状态",
        "response_fields": ["task_id", "slave_addr", "task_status"],
    },
    {
        "name": "afn06_request_time",
        "afn": 0x06, "fn": 1, "di": "E8060601",
        "direction": "downlink", "has_address": False,
        "description": "请求集中器时间",
    },
    {
        "name": "afn07_file_transfer_start",
        "afn": 0x07, "fn": 1, "di": "E8020701",
        "direction": "downlink", "has_address": False,
        "description": "启动文件传输",
        "request_fields": [
            "file_type", "file_id", "dest_addr", "total_segments",
            "file_size", "file_crc", "timeout_minutes",
        ],
    },
    {
        "name": "afn07_file_transfer_data",
        "afn": 0x07, "fn": 2, "di": "E8020702",
        "direction": "downlink", "has_address": False,
        "description": "传输文件内容",
        "request_fields": ["segment_index", "segment_length", "segment_data", "segment_crc"],
    },
    {
        "name": "afn07_query_file_info",
        "afn": 0x07, "fn": 3, "di": "E8000703",
        "direction": "downlink", "has_address": False,
        "description": "查询文件信息",
    },
    {
        "name": "afn07_query_progress",
        "afn": 0x07, "fn": 4, "di": "E8000704",
        "direction": "downlink", "has_address": False,
        "description": "查询文件处理进度",
    },
]

CSG_FIELD_DEFAULTS = {
    "result":       0x00,
    "error_code":   0x01,
    "task_id":      0x00,
    "task_mode_word": 0x10,
    "timeout_seconds": 70,
    "payload":      "FFFFFFFFFF",
    "payload_length": 5,
    "address_area.asrc": "000000000000",
    "address_area.adst": "012400038813",
    "task_count":   0x01,
    "remaining_task_count": 1,
    "start_task_index": 0,
    "query_task_count": 1,
    "reported_task_count": 1,
    "task_ids":     [1],
    "dest_addr_count": 1,
    "dest_addrs":   ["012400038813"],
    "enable":       0x01,
    "delay_time":   0x01,
    "task_status":  0x01,
    "slave_addr":   "012400038813",
    "slave_count":  1,
    "slave_addrs":  ["012400038813"],
    "slave_total":  1,
    "start_slave_index": 0,
    "response_slave_count": 1,
    "local_mode_word": 0x01,
    "max_protocol_frame_length": 500,
    "max_file_packet_length": 200,
    "upgrade_wait_minutes": 30,
    "master_addr":  "000000000000",
    "max_slave_count": 100,
    "current_slave_count": 1,
    "max_slave_rw_count": 32,
    "protocol_release_date": {"year": "26", "month": "06", "day": "21"},
    "file_type":    0x02,
    "file_id":      0x00,
    "dest_addr":    "999999999999",
    "total_segments": 1,
    "file_size":    2,
    "file_crc":     0xABCD,
    "timeout_minutes": 30,
    "received_segments": 0,
    "progress":     0,
    "unfinished_file_id": 0,
    "failed_node_count": 0,
    "start_node_index": 0,
    "query_node_count": 1,
    "node_total":   1,
    "response_node_count": 1,
    "node_addrs":   ["012400038813"],
    "segment_index": 0,
    "segment_length": 2,
    "segment_data": bytes([0xAA, 0xBB]),
    "segment_crc":  0xABCD,
    "vendor_code":  ["A", "B"],
    "chip_code":    ["0", "1"],
    "version_date": {"year": "26", "month": "06", "day": "21"},
    "version":      "1020",
    "datetime":     "2026062120",
}
