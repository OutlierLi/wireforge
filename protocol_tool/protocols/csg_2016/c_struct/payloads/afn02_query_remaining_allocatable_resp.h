/* @wireforge di=E8000206 desc=返回查询剩余可分配任务数 */
typedef struct __attribute__((packed)) {
    uint16_t remaining_task_count; /* @desc 剩余可分配任务数 */
} afn02_query_remaining_allocatable_resp_t;
