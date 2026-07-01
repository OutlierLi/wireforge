/* @wireforge func=0x19 di=00991901 dir=downlink desc="最大需量清零扩展" */
typedef struct __attribute__((packed)) {
    uint8_t demand_slot; /* @desc 需量时段序号 */
} clear_demand_ext_t;
