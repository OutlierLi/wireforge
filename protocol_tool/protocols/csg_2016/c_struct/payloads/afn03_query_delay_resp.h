/* @wireforge di=E8040304 desc=返回查询通信延时时长 */
typedef struct __attribute__((packed)) {
    node_address_t dest_addr; /* @desc 通信目的地址 @domain node_address */
    uint16_t delay_time; /* @desc 通信延时时长(秒) */
    uint8_t payload_length; /* @desc 报文长度 */
} afn03_query_delay_resp_t;
