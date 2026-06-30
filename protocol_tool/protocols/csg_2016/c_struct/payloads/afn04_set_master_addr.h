/* @wireforge di=E8020401 desc=设置主节点地址 */
typedef struct __attribute__((packed)) {
    node_address_t master_addr; /* @desc 主节点地址 @domain node_address */
} afn04_set_master_addr_t;
