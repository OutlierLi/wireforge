/* @wireforge di=E8050501 desc=上报任务数据 */
typedef struct __attribute__((packed)) {
    uint16_t task_id; /* @desc 任务ID */
    uint8_t payload_length; /* @desc 报文长度 */
    uint8_t payload[]; /* @desc 原始报文内容 @length_ref payload_length @hex */
} afn05_report_task_data_t;
