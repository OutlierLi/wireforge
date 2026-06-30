/* @wireforge afn=04 di=E8020499 dir=downlink desc="嵌套BCD时钟示例" */
typedef struct __attribute__((packed)) {
    struct {
        uint8_t second[1]; /* @desc 秒 @alias bcd */
        uint8_t minute[1]; /* @desc 分 @alias bcd */
        uint8_t hour[1]; /* @desc 时 @alias bcd */
        uint8_t day[1]; /* @desc 日 @alias bcd */
        uint8_t month[1]; /* @desc 月 @alias bcd */
        uint8_t year[1]; /* @desc 年(低字节) @alias bcd */
    } datetime; /* @desc CCO时钟 (ssmmhhDDMMYY) */
} nested_bcd_clock_t;
