/* @wireforge func=0x18 di=00991801 dir=downlink desc="修改密码扩展" */
typedef struct __attribute__((packed)) {
    struct {
        uint8_t old_pa; /* @desc 旧权限等级 */
        uint8_t old_p0; /* @desc 旧密码字节0 @hex */
        uint8_t old_p1; /* @desc 旧密码字节1 @hex */
        uint8_t old_p2; /* @desc 旧密码字节2 @hex */
    } password_block; /* @desc 密码块 */
} change_password_ext_t;
