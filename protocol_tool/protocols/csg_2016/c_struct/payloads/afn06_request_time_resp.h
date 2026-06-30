/* @wireforge di=E8060601 desc=请求集中器时间响应 */
typedef struct __attribute__((packed)) {
    struct {
        uint8_t second[1]; /* @desc 秒 @alias bcd */
        uint8_t minute[1]; /* @desc 分 @alias bcd */
        uint8_t hour[1]; /* @desc 时 @alias bcd */
        uint8_t day[1]; /* @desc 日 @alias bcd */
        uint8_t month[1]; /* @desc 月 @alias bcd */
        uint8_t year[1]; /* @desc 年 @alias bcd */
    } datetime; /* @desc 集中器当前时间 (ssmmhhDDMMYY) */
} afn06_request_time_resp_t;
