/* @wireforge di=E8000305 desc=返回查询从节点数量 */
typedef struct __attribute__((packed)) {
    uint16_t slave_total; /* @desc 从节点总数量 */
} afn03_query_slave_count_resp_t;
