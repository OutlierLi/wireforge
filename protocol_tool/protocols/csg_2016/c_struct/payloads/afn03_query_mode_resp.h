/* @wireforge di=E8000302 desc=返回本地通信模块运行模式信息 */
typedef struct __attribute__((packed)) {
    uint8_t local_mode_word; /* @desc 本地通信模式字 */
    uint16_t max_protocol_frame_length; /* @desc 最大支持的协议报文长度 */
    uint16_t max_file_packet_length; /* @desc 文件传输最大单包长度 */
    uint8_t upgrade_wait_minutes; /* @desc 升级操作等待时间(分钟) */
    node_address_t master_addr; /* @desc 主节点地址 @domain node_address */
    uint16_t max_slave_count; /* @desc 支持的最大从节点数量 */
    uint16_t current_slave_count; /* @desc 当前从节点数量 */
    uint16_t max_slave_rw_count; /* @desc 支持单次读写从节点信息的最大数量 */
    struct {
        uint8_t year[1]; /* @alias bcd */
        uint8_t month[1]; /* @alias bcd */
        uint8_t day[1]; /* @alias bcd */
    } protocol_release_date; /* @desc 通信模块接口协议发布日期(YYMMDD) */
    char vendor_code[2];
    char chip_code[2];
    struct {
        uint8_t year[1]; /* @alias bcd */
        uint8_t month[1]; /* @alias bcd */
        uint8_t day[1]; /* @alias bcd */
    } version_date; /* @desc 版本日期(YYMMDD) */
    uint8_t version[2]; /* @alias bcd */
} afn03_query_mode_resp_t;
