/* @wireforge di=E8000307 desc=返回查询从节点主动注册进度 */
typedef struct __attribute__((packed)) {
    uint8_t register_status; /* @desc 从节点主动注册工作标示 */
} afn03_query_slave_register_progress_resp_t;
