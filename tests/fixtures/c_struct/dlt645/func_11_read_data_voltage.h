/* @wireforge func=0x11 di=00991102 dir=uplink desc="读数据应答-电压" */
typedef struct __attribute__((packed)) {
    uint16_t voltage; /* @desc A相电压 @unit V @alias bcd */
} read_data_voltage_t;
