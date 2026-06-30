/* @wireforge di=E8030306 desc=查询从节点信息 */
typedef struct __attribute__((packed)) {
    uint16_t start_slave_index; /* @desc 从节点起始序号 */
    uint8_t slave_count; /* @desc 从节点数量 */
} afn03_query_slave_info_t;
