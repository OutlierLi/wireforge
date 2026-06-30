/* @wireforge di=E8050505 desc=上报任务状态 */
typedef struct __attribute__((packed)) {
    uint16_t task_id; /* @desc 任务ID */
    node_address_t slave_addr; /* @desc 从节点地址 @domain node_address */
    uint8_t task_status; /* @desc 任务状态 */
} afn05_report_task_status_t;
