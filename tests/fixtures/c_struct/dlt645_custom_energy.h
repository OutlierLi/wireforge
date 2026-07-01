/* @wireforge func=0x11 di=00099999 dir=uplink desc="自定义扩展电能量" */
typedef struct __attribute__((packed)) {
    uint8_t rate_index; /* @desc 费率序号 @enum 0x00:总 0x01:费率1 */
    uint32_t energy_raw; /* @desc 电能量原始值 */
} custom_energy_t;
