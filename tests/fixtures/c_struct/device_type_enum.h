/* @wireforge afn=03 di=E8039998 dir=uplink desc="设备类型枚举示例" */
typedef struct __attribute__((packed)) {
    uint8_t device_type; /* @desc 设备类型 @enum 0x00:单相表 0x01:三相表 0x02:采集器 0x03:集中器 */
} device_type_enum_t;
