/* @wireforge di=E8040205 desc=返回查询未完成任务详细信息 */
typedef struct __attribute__((packed)) {
    uint16_t task_id; /* @desc 任务ID */
    uint8_t task_mode_word; /* @desc 任务模式字 */
    uint16_t dest_addr_count; /* @desc 目的地址数量 */
    node_address_t dest_addrs[]; /* @desc 目的地址列表 @count_ref dest_addr_count @item_name dest_addr @domain node_address */
    uint8_t payload_length; /* @desc 报文长度 */
    uint8_t payload[]; /* @desc 原始报文内容 @length_ref payload_length @hex */
} afn02_query_task_detail_resp_t;
