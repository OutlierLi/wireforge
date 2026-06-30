/* @wireforge di=E8020403 desc=删除从节点 */
typedef struct __attribute__((packed)) {
    uint8_t slave_count; /* @desc 从节点数量 */
    node_address_t slave_addrs[]; /* @desc 从节点地址列表 @count_ref slave_count @item_name slave_addr @domain node_address */
} afn04_delete_slave_t;
