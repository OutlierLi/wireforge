/* @wireforge func=0x16 di=00991601 dir=downlink desc="冻结命令扩展" */
typedef struct __attribute__((packed)) {
    bcd_datetime_t freeze_time; /* @domain bcd_datetime @desc 冻结时间 */
} freeze_ext_t;
