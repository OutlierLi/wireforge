/* @wireforge func=0x11 di=00991103 dir=uplink desc="读数据应答-日期时间" */
typedef struct __attribute__((packed)) {
    struct {
        uint8_t second[1]; /* @alias bcd @desc 秒 */
        uint8_t minute[1]; /* @alias bcd @desc 分 */
        uint8_t hour[1]; /* @alias bcd @desc 时 */
        uint8_t day[1]; /* @alias bcd @desc 日 */
        uint8_t month[1]; /* @alias bcd @desc 月 */
        uint8_t year[1]; /* @alias bcd @desc 年 */
    } datetime; /* @desc 当前日期时间 */
} read_data_datetime_t;
