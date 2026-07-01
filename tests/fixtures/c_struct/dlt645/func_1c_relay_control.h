/* @wireforge func=0x1C di=00991C01 dir=downlink desc="跳合闸控制扩展" */
typedef struct __attribute__((packed)) {
    struct {
        uint8_t direct_close : 1; /* @desc 直接合闸 */
        uint8_t allow_close : 1; /* @desc 允许合闸 */
        uint8_t direct_trip : 1; /* @desc 直接跳闸 */
        uint8_t reserved : 5; /* @desc 保留位 */
    } control_bits; /* @desc 控制字 */
} relay_control_ext_t;
