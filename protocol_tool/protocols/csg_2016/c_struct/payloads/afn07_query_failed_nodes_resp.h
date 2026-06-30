/* @wireforge di=E8040704 desc=返回查询文件传输失败节点 */
typedef struct __attribute__((packed)) {
    uint16_t node_total; /* @desc 节点总数量 */
    uint8_t response_node_count; /* @desc 本次应答的节点数量 */
    node_address_t node_addrs[]; /* @desc 节点地址列表 @count_ref response_node_count @item_name node_addr @domain node_address */
} afn07_query_failed_nodes_resp_t;
