/* @wireforge afn=03 di=E8039999 dir=downlink desc="查询从节点信息" */
typedef struct __attribute__((packed)) {
    uint16_t start_slave_index; /* @desc 起始从节点序号 */
    uint8_t slave_count;        /* @desc 从节点数量 */
} query_slave_info_req_t;
