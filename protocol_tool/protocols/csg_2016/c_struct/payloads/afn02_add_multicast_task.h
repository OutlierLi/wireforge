/* @wireforge di=E8020207 desc=添加多播任务（选配） */
typedef struct __attribute__((packed)) {
    uint16_t task_id; /* @desc 任务ID */
    uint8_t task_mode_word; /* @desc 任务模式字 */
    uint16_t slave_count; /* @desc 从节点数量,0xFFFF 表示广播 */
    node_address_t slave_addrs[]; /* @desc 从节点地址列表 @count_ref slave_count @item_name slave_addr @domain node_address */
    uint16_t timeout_seconds; /* @desc 任务执行超时时间(秒) */
    uint8_t payload_length; /* @desc 报文长度 */
    uint8_t payload[]; /* @desc 原始报文内容 @length_ref payload_length @hex */
} afn02_add_multicast_task_t;
