/* @wireforge func=0x08 di=00990801 dir=downlink desc="广播校时扩展" */
typedef struct __attribute__((packed)) {
    bcd_datetime_t clock; /* @domain bcd_datetime @desc 校时时间 */
} broadcast_time_ext_t;
