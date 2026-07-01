/* @wireforge func=0x1A di=00991A01 dir=downlink desc="电表清零扩展" */
typedef struct __attribute__((packed)) {
    uint8_t clear_flag; /* @desc 清零标志 @enum 0x00:保留 0x01:执行 */
} clear_meter_ext_t;
