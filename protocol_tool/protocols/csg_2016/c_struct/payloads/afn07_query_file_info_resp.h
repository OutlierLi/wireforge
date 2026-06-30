/* @wireforge di=E8000703 desc=返回查询文件信息 */
typedef struct __attribute__((packed)) {
    uint8_t file_type; /* @desc 文件性质 */
    uint8_t file_id; /* @desc 文件ID */
    node_address_t dest_addr; /* @desc 目的地址 @domain node_address */
    uint16_t total_segments; /* @desc 文件总段数 */
    uint32_t file_size; /* @desc 文件大小 */
    uint16_t file_crc; /* @desc 文件总校验 */
    uint16_t received_segments; /* @desc 已成功接收文件段数 */
} afn07_query_file_info_resp_t;
