/* @wireforge di=E8040308 desc=返回查询从节点的父节点 */
typedef struct __attribute__((packed)) {
    node_address_t slave_addr; /* @desc 从节点地址 @domain node_address */
    node_address_t parent_addr; /* @desc 父节点地址 @domain node_address */
    uint8_t link_quality; /* @desc 链路质量 */
} afn03_query_slave_parent_resp_t;
