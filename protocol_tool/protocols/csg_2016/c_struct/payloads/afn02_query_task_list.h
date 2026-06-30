/* @wireforge di=E8030204 desc=查询未完成任务列表 */
typedef struct __attribute__((packed)) {
    uint16_t start_task_index; /* @desc 起始任务序号,序号从0开始 */
    uint8_t query_task_count; /* @desc 查询任务数量 */
} afn02_query_task_list_t;
