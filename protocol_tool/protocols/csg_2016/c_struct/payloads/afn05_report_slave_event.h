/* @wireforge di=E8050502 desc=上报从节点事件 */
typedef struct __attribute__((packed)) {
    uint8_t payload_length; /* @desc 报文长度 */
    uint8_t payload[]; /* @desc 状态字原始报文内容 @length_ref payload_length @hex */
} afn05_report_slave_event_t;
