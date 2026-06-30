/* @wireforge di=E8000704 desc=返回查询文件处理进度 */
typedef struct __attribute__((packed)) {
    uint8_t progress; /* @desc 文件处理进度 */
    uint8_t unfinished_file_id; /* @desc 处理未完成的文件ID */
    uint16_t failed_node_count; /* @desc 失败节点数量 */
} afn07_query_progress_resp_t;
