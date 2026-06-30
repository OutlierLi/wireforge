/* @wireforge di=E8040306 desc=返回查询从节点信息 */
typedef struct __attribute__((packed)) {
    uint16_t slave_total; /* @desc 从节点总数量 */
    uint8_t response_slave_count; /* @desc 本次应答的从节点数量 */
    node_address_t slave_addrs[]; /* @desc 从节点地址列表 @count_ref response_slave_count @item_name slave_addr @domain node_address */
} afn03_query_slave_info_resp_t;
