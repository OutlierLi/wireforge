/* @wireforge afn=04 di=E80204A3 dir=downlink desc="设置CCO时钟" */
typedef struct __attribute__((packed)) {
    bcd_datetime_t datetime; /* @domain bcd_datetime @desc CCO时钟 (ssmmhhDDMMYY) */
} set_cco_time_t;
