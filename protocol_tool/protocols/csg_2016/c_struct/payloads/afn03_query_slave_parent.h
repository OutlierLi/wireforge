/* @wireforge di=E8030308 desc=查询从节点的父节点 */
typedef struct __attribute__((packed)) {
    node_address_t slave_addr; /* @desc 从节点地址 @domain node_address */
} afn03_query_slave_parent_t;
