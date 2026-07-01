/* @wireforge func=0x15 di=00991501 dir=downlink desc="写通信地址扩展" */
typedef struct __attribute__((packed)) {
    uint8_t confirm_code; /* @desc 确认码 @enum 0x00:取消 0x01:确认 */
} write_address_ext_t;
