/* @wireforge di=E8050503 desc=上报从节点信息 */
typedef struct __attribute__((packed)) {
    uint8_t slave_count; /* @desc 上报从节点数量 */
    node_address_t slave_addrs[]; /* @desc 从节点地址列表 @count_ref slave_count @item_name slave_addr @domain node_address */
} afn05_report_slave_info_t;
