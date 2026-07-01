/* @wireforge func=0x14 di=00991401 dir=downlink desc="写数据请求载荷扩展" */
typedef struct __attribute__((packed)) {
    uint16_t write_value; /* @desc 写入数值 */
} write_data_ext_t;
