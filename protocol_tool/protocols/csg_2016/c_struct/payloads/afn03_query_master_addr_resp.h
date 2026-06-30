/* @wireforge di=E8000303 desc=返回主节点地址 */
typedef struct __attribute__((packed)) {
    node_address_t master_addr; /* @desc 主节点地址 @domain node_address */
} afn03_query_master_addr_resp_t;
