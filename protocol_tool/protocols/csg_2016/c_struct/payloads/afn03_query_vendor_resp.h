/* @wireforge di=E8000301 desc=返回厂商代码和版本信息 */
typedef struct __attribute__((packed)) {
    char vendor_code[2];
    char chip_code[2];
    struct {
        uint8_t year[1]; /* @desc 年 @alias bcd */
        uint8_t month[1]; /* @desc 月 @alias bcd */
        uint8_t day[1]; /* @desc 日 @alias bcd */
    } version_date; /* @desc 版本日期 (YYMMDD) */
    uint8_t version[2]; /* @alias bcd */
} afn03_query_vendor_resp_t;
