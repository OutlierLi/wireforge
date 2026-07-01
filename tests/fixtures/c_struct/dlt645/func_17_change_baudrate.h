/* @wireforge func=0x17 di=00991701 dir=downlink desc="更改通信速率扩展" */
typedef struct __attribute__((packed)) {
    uint8_t baud_rate; /* @desc 波特率特征字 @enum 0x02:600 0x04:2400 0x08:9600 */
} change_baudrate_ext_t;
