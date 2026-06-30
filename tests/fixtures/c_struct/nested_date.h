/* @wireforge afn=03 di=E8039997 dir=uplink desc="嵌套结构体示例" */
typedef struct __attribute__((packed)) {
    struct {
        uint8_t year;  /* @desc 年 */
        uint8_t month; /* @desc 月 */
        uint8_t day;   /* @desc 日 */
    } protocol_release_date; /* @desc 协议发布日期 */
} nested_date_t;
