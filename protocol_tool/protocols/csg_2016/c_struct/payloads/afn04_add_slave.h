/* @wireforge di=E8020402 desc=添加从节点 */
typedef struct __attribute__((packed)) {
    uint8_t slave_count; /* @desc 从节点数量 */
    node_address_t slave_addrs[]; /* @desc 从节点地址列表 @count_ref slave_count @item_name slave_addr @domain node_address */
} afn04_add_slave_t;
