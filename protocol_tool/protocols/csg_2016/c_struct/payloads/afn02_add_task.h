/* @wireforge di=E8020201 desc=添加任务 */
typedef struct __attribute__((packed)) {
    uint16_t task_id; /* @desc 任务ID,区分不同任务的任务标识,取值范围0x0000-0xEFFF @default 0 */
    uint8_t task_mode_word; /* @desc 任务模式字,D7为任务响应标识,D3-D0为任务优先级 @default 16 */
    uint16_t timeout_seconds; /* @desc 任务执行超时时间(秒) @default 70 */
    uint8_t payload_length; /* @desc 报文长度 */
    uint8_t payload[]; /* @desc 原始报文内容 @length_ref payload_length @hex */
} afn02_add_task_t;
