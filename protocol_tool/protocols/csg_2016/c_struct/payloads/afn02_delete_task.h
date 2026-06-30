/* @wireforge di=E8020202 desc=删除任务 */
typedef struct __attribute__((packed)) {
    uint16_t task_id; /* @desc 任务ID,区分不同任务的任务标识,取值范围0x0000-0xEFFF */
} afn02_delete_task_t;
