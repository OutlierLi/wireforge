/* @wireforge di=E8030304 desc=查询通信延时时长 */
typedef struct __attribute__((packed)) {
    node_address_t dest_addr; /* @desc 通信目的地址 @domain node_address */
    uint8_t payload_length; /* @desc 报文长度 */
} afn03_query_delay_t;
