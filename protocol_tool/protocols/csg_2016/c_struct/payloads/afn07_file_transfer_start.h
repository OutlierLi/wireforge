/* @wireforge di=E8020701 desc=启动文件传输 */
typedef struct __attribute__((packed)) {
    uint8_t file_type; /* @desc 文件性质 */
    uint8_t file_id; /* @desc 文件ID */
    node_address_t dest_addr; /* @desc 目的地址 @domain node_address */
    uint16_t total_segments; /* @desc 文件总段数 */
    uint32_t file_size; /* @desc 文件大小 */
    uint16_t file_crc; /* @desc 文件总校验 */
    uint8_t timeout_minutes; /* @desc 文件传输超时时间(分钟) */
} afn07_file_transfer_start_t;
