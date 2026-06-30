/* @wireforge di=E8040204 desc=返回查询未完成任务列表 */
typedef struct __attribute__((packed)) {
    uint16_t reported_task_count; /* @desc 上报任务数量 */
    uint16_t task_ids[]; /* @desc 任务ID列表 @count_ref reported_task_count @item_name task_id */
} afn02_query_task_list_resp_t;
