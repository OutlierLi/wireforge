/* @wireforge di=E8000103 desc=返回查询未完成任务数 */
typedef struct __attribute__((packed)) {
    uint16_t task_count; /* @desc 未完成任务数量 */
} afn02_query_remaining_resp_t;
