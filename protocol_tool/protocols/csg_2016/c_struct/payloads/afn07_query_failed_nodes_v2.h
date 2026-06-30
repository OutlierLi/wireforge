/* @wireforge di=E8030705 desc=查询文件传输失败节点 */
typedef struct __attribute__((packed)) {
    uint16_t start_node_index; /* @desc 节点起始序号 */
    uint8_t query_node_count; /* @desc 本次查询的节点数量 */
} afn07_query_failed_nodes_v2_t;
