/* @wireforge di=E8020702 desc=传输文件内容 */
typedef struct __attribute__((packed)) {
    uint16_t segment_index; /* @desc 文件段号 */
    uint16_t segment_length; /* @desc 文件段长度 */
    uint8_t segment_data[]; /* @desc 文件段内容 @length_ref segment_length @hex */
    uint16_t segment_crc; /* @desc 文件段校验 */
} afn07_file_transfer_data_t;
